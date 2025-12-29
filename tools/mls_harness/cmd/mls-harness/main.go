package main

import (
	"bytes"
	crand "crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"encoding/gob"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"hash"
	"math/rand"
	"os"
	"path/filepath"
	"strings"

	mls "github.com/cisco/go-mls"
	syntax "github.com/cisco/go-tls-syntax"
)

type participant struct {
	name        string
	initSecret  []byte
	identityKey mls.SignaturePrivateKey
	keyPackage  mls.KeyPackage
	state       *mls.State
}

func main() {
	if len(os.Args) < 2 {
		usage()
	}

	switch os.Args[1] {
	case "smoke":
		smoke := flag.NewFlagSet("smoke", flag.ExitOnError)
		iterations := smoke.Int("iterations", 50, "number of message iterations per participant")
		saveEvery := smoke.Int("save-every", 10, "checkpoint interval for persisting state")
		stateDir := smoke.String("state-dir", "", "directory to store state snapshots")
		if err := smoke.Parse(os.Args[2:]); err != nil {
			fmt.Fprintf(os.Stderr, "failed to parse smoke flags: %v\n", err)
			os.Exit(2)
		}

		if err := runSmoke(*iterations, *saveEvery, *stateDir); err != nil {
			fmt.Fprintf(os.Stderr, "smoke scenario failed: %v\n", err)
			os.Exit(1)
		}
	case "vectors":
		vectors := flag.NewFlagSet("vectors", flag.ExitOnError)
		vectorFile := vectors.String("vector-file", "", "path to vector JSON file")
		if err := vectors.Parse(os.Args[2:]); err != nil {
			fmt.Fprintf(os.Stderr, "failed to parse vectors flags: %v\n", err)
			os.Exit(2)
		}

		if err := runVectors(*vectorFile); err != nil {
			fmt.Fprintf(os.Stderr, "vector verification failed: %v\n", err)
			os.Exit(1)
		}
	case "soak":
		soak := flag.NewFlagSet("soak", flag.ExitOnError)
		iterations := soak.Int("iterations", 1000, "number of message iterations per participant")
		saveEvery := soak.Int("save-every", 50, "checkpoint interval for persisting state")
		stateDir := soak.String("state-dir", "", "directory to store state snapshots")
		if err := soak.Parse(os.Args[2:]); err != nil {
			fmt.Fprintf(os.Stderr, "failed to parse soak flags: %v\n", err)
			os.Exit(2)
		}

		if err := runSmoke(*iterations, *saveEvery, *stateDir); err != nil {
			fmt.Fprintf(os.Stderr, "soak scenario failed: %v\n", err)
			os.Exit(1)
		}
	default:
		usage()
	}
}

func usage() {
	fmt.Fprintf(os.Stderr, "usage: mls-harness <smoke|vectors|soak> [flags]\n")
	os.Exit(2)
}

func runSmoke(iterations, saveEvery int, stateDir string) error {
	if iterations <= 0 {
		return fmt.Errorf("iterations must be positive (got %d)", iterations)
	}
	if saveEvery <= 0 {
		return fmt.Errorf("save-every must be positive (got %d)", saveEvery)
	}
	if stateDir == "" {
		return errors.New("state-dir is required")
	}

	if err := os.MkdirAll(stateDir, 0o700); err != nil {
		return fmt.Errorf("failed to create state-dir: %w", err)
	}

	rng := deterministicRNG()
	restore := overrideCryptoRand(rng)
	defer restore()

	alice, bob, err := bootstrapPair(rng)
	if err != nil {
		return fmt.Errorf("failed to bootstrap participants: %w", err)
	}

	for i := 0; i < iterations; i++ {
		payload := []byte(fmt.Sprintf("msg-%d", i))

		if err := exchangeOnceWithDigest(alice, bob, payload, "", nil); err != nil {
			return fmt.Errorf("iteration %d alice->bob: %w", i, err)
		}

		if err := exchangeOnceWithDigest(bob, alice, payload, "", nil); err != nil {
			return fmt.Errorf("iteration %d bob->alice: %w", i, err)
		}

		if (i+1)%saveEvery == 0 {
			if err := persistRoundTrip(stateDir, alice, bob); err != nil {
				return fmt.Errorf("iteration %d persistence: %w", i, err)
			}
		}
	}

	return nil
}

type vectorSpec struct {
	Name       string `json:"name"`
	Suite      string `json:"cipher_suite"`
	Iterations int    `json:"iterations"`
	DigestHex  string `json:"digest_sha256_hex"`
}

func runVectors(vectorPath string) error {
	if vectorPath == "" {
		return errors.New("vector-file is required")
	}

	spec, err := loadVectorSpec(vectorPath)
	if err != nil {
		return fmt.Errorf("load vector spec: %w", err)
	}

	rng := deterministicRNG()
	restore := overrideCryptoRand(rng)
	defer restore()
	dig := newTranscriptDigest()

	alice, bob, err := bootstrapPairWithDigest(rng, dig)
	if err != nil {
		return fmt.Errorf("failed to bootstrap participants: %w", err)
	}

	for i := 0; i < spec.Iterations; i++ {
		payload := []byte(fmt.Sprintf("msg-%d", i))

		aliceLabel := fmt.Sprintf("iter-%d-%s-%s", i, alice.name, bob.name)
		if err := exchangeOnceWithDigest(alice, bob, payload, aliceLabel, dig); err != nil {
			return fmt.Errorf("iteration %d alice->bob: %w", i, err)
		}

		bobLabel := fmt.Sprintf("iter-%d-%s-%s", i, bob.name, alice.name)
		if err := exchangeOnceWithDigest(bob, alice, payload, bobLabel, dig); err != nil {
			return fmt.Errorf("iteration %d bob->alice: %w", i, err)
		}
	}

	computed := dig.hexSum()
	expected := strings.ToLower(spec.DigestHex)
	if computed != expected {
		return fmt.Errorf("digest mismatch: computed %s expected %s", computed, expected)
	}

	fmt.Println("ok")
	return nil
}

func exchangeOnce(sender, receiver *participant, msg []byte) error {
	return exchangeOnceWithDigest(sender, receiver, msg, "", nil)
}

func exchangeOnceWithDigest(sender, receiver *participant, msg []byte, label string, dig *transcriptDigest) error {
	ct, err := sender.state.Protect(msg)
	if err != nil {
		return fmt.Errorf("protect failed for %s: %w", sender.name, err)
	}

	if dig != nil {
		if err := dig.addCiphertext(label, ct); err != nil {
			return fmt.Errorf("digest update failed: %w", err)
		}
	}

	pt, err := receiver.state.Unprotect(ct)
	if err != nil {
		return fmt.Errorf("unprotect failed for %s: %w", receiver.name, err)
	}

	if !bytes.Equal(pt, msg) {
		return fmt.Errorf("plaintext mismatch for %s -> %s", sender.name, receiver.name)
	}

	return nil
}

func persistRoundTrip(stateDir string, alice, bob *participant) error {
	if err := saveState(filepath.Join(stateDir, "alice.gob"), alice.state); err != nil {
		return fmt.Errorf("alice persist: %w", err)
	}
	if err := saveState(filepath.Join(stateDir, "bob.gob"), bob.state); err != nil {
		return fmt.Errorf("bob persist: %w", err)
	}

	restoredAlice, err := loadState(filepath.Join(stateDir, "alice.gob"))
	if err != nil {
		return fmt.Errorf("alice reload: %w", err)
	}
	restoredBob, err := loadState(filepath.Join(stateDir, "bob.gob"))
	if err != nil {
		return fmt.Errorf("bob reload: %w", err)
	}

	alice.state = restoredAlice
	bob.state = restoredBob
	return nil
}

func saveState(path string, state *mls.State) error {
	registerStateTypes(state)

	var buf bytes.Buffer
	if err := gob.NewEncoder(&buf).Encode(state); err != nil {
		return fmt.Errorf("encode: %w", err)
	}
	if err := os.WriteFile(path, buf.Bytes(), 0o600); err != nil {
		return fmt.Errorf("write: %w", err)
	}
	return nil
}

func loadState(path string) (*mls.State, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read: %w", err)
	}
	var state mls.State
	if err := gob.NewDecoder(bytes.NewReader(data)).Decode(&state); err != nil {
		return nil, fmt.Errorf("decode: %w", err)
	}
	return &state, nil
}

func bootstrapPair(rng *rand.Rand) (*participant, *participant, error) {
	return bootstrapPairWithDigest(rng, nil)
}

func newParticipant(rng *rand.Rand, suite mls.CipherSuite, name string) (*participant, error) {
	secret := randomBytes(rng, 32)
	scheme := suite.Scheme()
	sigPriv, err := scheme.Derive(secret)
	if err != nil {
		return nil, fmt.Errorf("derive identity key: %w", err)
	}
	cred := mls.NewBasicCredential([]byte(name), scheme, sigPriv.PublicKey)
	kp, err := mls.NewKeyPackageWithSecret(suite, secret, cred, sigPriv)
	if err != nil {
		return nil, fmt.Errorf("create key package: %w", err)
	}

	if err := makeKeyPackageDeterministic(kp, sigPriv); err != nil {
		return nil, fmt.Errorf("stabilize key package: %w", err)
	}

	return &participant{
		name:        name,
		initSecret:  secret,
		identityKey: sigPriv,
		keyPackage:  *kp,
	}, nil
}

func randomBytes(rng *rand.Rand, n int) []byte {
	b := make([]byte, n)
	if _, err := rng.Read(b); err != nil {
		panic(err)
	}
	return b
}

func init() {
	gob.Register(&mls.State{})
}

func deterministicRNG() *rand.Rand {
	rand.Seed(42)
	return rand.New(rand.NewSource(1337))
}

func overrideCryptoRand(rng *rand.Rand) func() {
	original := crand.Reader
	crand.Reader = rng
	return func() {
		crand.Reader = original
	}
}

func makeKeyPackageDeterministic(kp *mls.KeyPackage, sigPriv mls.SignaturePrivateKey) error {
	const deterministicExpiry uint64 = 4_102_444_800 // 2100-01-01 00:00:00 UTC

	lifetime := mls.LifetimeExtension{NotBefore: 0, NotAfter: deterministicExpiry}
	if err := kp.Extensions.Add(lifetime); err != nil {
		return fmt.Errorf("set lifetime extension: %w", err)
	}

	if err := kp.Sign(sigPriv); err != nil {
		return fmt.Errorf("re-sign key package: %w", err)
	}

	return nil
}

func bootstrapPairWithDigest(rng *rand.Rand, dig *transcriptDigest) (*participant, *participant, error) {
	suite := mls.X25519_AES128GCM_SHA256_Ed25519

	alice, err := newParticipant(rng, suite, "alice")
	if err != nil {
		return nil, nil, fmt.Errorf("alice init: %w", err)
	}
	bob, err := newParticipant(rng, suite, "bob")
	if err != nil {
		return nil, nil, fmt.Errorf("bob init: %w", err)
	}

	groupID := []byte{0x01, 0x02, 0x03, 0x04}
	if dig != nil {
		if err := dig.addBytes("group-id", groupID); err != nil {
			return nil, nil, fmt.Errorf("digest group id: %w", err)
		}
		if err := dig.addKeyPackage("alice-key-package", alice.keyPackage); err != nil {
			return nil, nil, fmt.Errorf("digest alice key package: %w", err)
		}
		if err := dig.addKeyPackage("bob-key-package", bob.keyPackage); err != nil {
			return nil, nil, fmt.Errorf("digest bob key package: %w", err)
		}
	}

	alice.state, err = mls.NewEmptyState(groupID, alice.initSecret, alice.identityKey, alice.keyPackage)
	if err != nil {
		return nil, nil, fmt.Errorf("create group: %w", err)
	}

	add, err := alice.state.Add(bob.keyPackage)
	if err != nil {
		return nil, nil, fmt.Errorf("add bob: %w", err)
	}
	if dig != nil {
		if err := dig.addMLSPlaintext("add", add); err != nil {
			return nil, nil, fmt.Errorf("digest add: %w", err)
		}
	}
	if _, err = alice.state.Handle(add); err != nil {
		return nil, nil, fmt.Errorf("handle add: %w", err)
	}

	commitSecret := randomBytes(rng, 32)
	commitPT, welcome, nextAlice, err := alice.state.Commit(commitSecret)
	if err != nil {
		return nil, nil, fmt.Errorf("commit: %w", err)
	}
	if dig != nil {
		if err := dig.addMLSPlaintext("commit", commitPT); err != nil {
			return nil, nil, fmt.Errorf("digest commit: %w", err)
		}
		if err := dig.addWelcome("welcome", welcome); err != nil {
			return nil, nil, fmt.Errorf("digest welcome: %w", err)
		}
	}
	alice.state = nextAlice

	bob.state, err = mls.NewJoinedState(bob.initSecret, []mls.SignaturePrivateKey{bob.identityKey}, []mls.KeyPackage{bob.keyPackage}, *welcome)
	if err != nil {
		return nil, nil, fmt.Errorf("bob join: %w", err)
	}

	return alice, bob, nil
}

func registerStateTypes(state *mls.State) {
	if state == nil {
		return
	}

	registerValue(state.Keys)
	registerValue(state.Keys.HandshakeBaseKeys)
	registerValue(state.Keys.ApplicationBaseKeys)
	registerValue(state.Keys.HandshakeRatchets)
	registerValue(state.Keys.ApplicationRatchets)
	registerValue(state.Keys.HandshakeKeys)
	registerValue(state.Keys.ApplicationKeys)

	for _, ratchet := range state.Keys.HandshakeRatchets {
		registerValue(ratchet)
	}
	for _, ratchet := range state.Keys.ApplicationRatchets {
		registerValue(ratchet)
	}
}

func registerValue(v interface{}) {
	if v == nil {
		return
	}
	gob.Register(v)
}

type transcriptDigest struct {
	h hash.Hash
}

func newTranscriptDigest() *transcriptDigest {
	return &transcriptDigest{h: sha256.New()}
}

func (t *transcriptDigest) addBytes(label string, data []byte) error {
	if t == nil {
		return nil
	}
	if _, err := t.h.Write([]byte(label)); err != nil {
		return err
	}

	var lenBuf [4]byte
	binary.BigEndian.PutUint32(lenBuf[:], uint32(len(data)))
	if _, err := t.h.Write(lenBuf[:]); err != nil {
		return err
	}
	if _, err := t.h.Write(data); err != nil {
		return err
	}
	return nil
}

func (t *transcriptDigest) addKeyPackage(label string, kp mls.KeyPackage) error {
	data, err := syntax.Marshal(kp)
	if err != nil {
		return err
	}
	return t.addBytes(label, data)
}

func (t *transcriptDigest) addMLSPlaintext(label string, pt *mls.MLSPlaintext) error {
	if pt == nil {
		return fmt.Errorf("nil plaintext for label %s", label)
	}
	data, err := syntax.Marshal(pt)
	if err != nil {
		return err
	}
	return t.addBytes(label, data)
}

func (t *transcriptDigest) addWelcome(label string, welcome *mls.Welcome) error {
	if welcome == nil {
		return fmt.Errorf("nil welcome for label %s", label)
	}
	data, err := syntax.Marshal(*welcome)
	if err != nil {
		return err
	}
	return t.addBytes(label, data)
}

func (t *transcriptDigest) addCiphertext(label string, ct *mls.MLSCiphertext) error {
	if ct == nil {
		return fmt.Errorf("nil ciphertext for label %s", label)
	}
	data, err := syntax.Marshal(*ct)
	if err != nil {
		return err
	}
	return t.addBytes(label, data)
}

func (t *transcriptDigest) hexSum() string {
	if t == nil {
		return ""
	}
	return hex.EncodeToString(t.h.Sum(nil))
}

func loadVectorSpec(path string) (*vectorSpec, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read vector file: %w", err)
	}

	var spec vectorSpec
	if err := json.Unmarshal(data, &spec); err != nil {
		return nil, fmt.Errorf("unmarshal vector file: %w", err)
	}

	if spec.Name == "" {
		return nil, errors.New("vector name is required")
	}
	if spec.Suite != mls.X25519_AES128GCM_SHA256_Ed25519.String() {
		return nil, fmt.Errorf("unsupported cipher_suite %q", spec.Suite)
	}
	if spec.Iterations <= 0 {
		return nil, fmt.Errorf("iterations must be positive (got %d)", spec.Iterations)
	}
	if spec.DigestHex == "" {
		return nil, errors.New("digest_sha256_hex is required")
	}

	return &spec, nil
}
