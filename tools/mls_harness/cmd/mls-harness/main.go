package main

import (
	"bytes"
	crand "crypto/rand"
	"crypto/sha256"
	"encoding/base64"
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

type storedParticipant struct {
	Name       string
	InitSecret []byte
	State      *mls.State
	Pending    *pendingCommit
}

type pendingCommit struct {
	Commit    []byte
	Welcome   []byte
	NextState *mls.State
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
	case "dm-keypackage":
		dmKP := flag.NewFlagSet("dm-keypackage", flag.ExitOnError)
		name := dmKP.String("name", "participant", "participant name for credential")
		stateDir := dmKP.String("state-dir", "", "directory for participant state")
		seed := dmKP.Int64("seed", 1337, "deterministic RNG seed")
		if err := dmKP.Parse(os.Args[2:]); err != nil {
			fmt.Fprintf(os.Stderr, "failed to parse dm-keypackage flags: %v\n", err)
			os.Exit(2)
		}
		kp, err := runDMKeyPackage(*stateDir, *name, *seed)
		if err != nil {
			fmt.Fprintf(os.Stderr, "dm-keypackage failed: %v\n", err)
			os.Exit(1)
		}
		fmt.Println(kp)
	case "dm-init":
		dmInit := flag.NewFlagSet("dm-init", flag.ExitOnError)
		stateDir := dmInit.String("state-dir", "", "directory for participant state")
		peerKP := dmInit.String("peer-keypackage", "", "base64-encoded peer KeyPackage")
		groupID := dmInit.String("group-id", "ZHMtZG0tZ3JvdXA=", "base64 group ID")
		seed := dmInit.Int64("seed", 7331, "deterministic RNG seed for commit")
		if err := dmInit.Parse(os.Args[2:]); err != nil {
			fmt.Fprintf(os.Stderr, "failed to parse dm-init flags: %v\n", err)
			os.Exit(2)
		}
		welcome, commit, err := runDMInit(*stateDir, *peerKP, *groupID, *seed)
		if err != nil {
			fmt.Fprintf(os.Stderr, "dm-init failed: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("{\"welcome\":\"%s\",\"commit\":\"%s\"}\n", welcome, commit)
	case "dm-join":
		dmJoin := flag.NewFlagSet("dm-join", flag.ExitOnError)
		stateDir := dmJoin.String("state-dir", "", "directory for participant state")
		welcome := dmJoin.String("welcome", "", "base64-encoded Welcome message")
		if err := dmJoin.Parse(os.Args[2:]); err != nil {
			fmt.Fprintf(os.Stderr, "failed to parse dm-join flags: %v\n", err)
			os.Exit(2)
		}
		if err := runDMJoin(*stateDir, *welcome); err != nil {
			fmt.Fprintf(os.Stderr, "dm-join failed: %v\n", err)
			os.Exit(1)
		}
	case "dm-commit-apply":
		dmApply := flag.NewFlagSet("dm-commit-apply", flag.ExitOnError)
		stateDir := dmApply.String("state-dir", "", "directory for participant state")
		commit := dmApply.String("commit", "", "base64-encoded commit MLSPlaintext")
		if err := dmApply.Parse(os.Args[2:]); err != nil {
			fmt.Fprintf(os.Stderr, "failed to parse dm-commit-apply flags: %v\n", err)
			os.Exit(2)
		}
		if err := runDMCommitApply(*stateDir, *commit); err != nil {
			fmt.Fprintf(os.Stderr, "dm-commit-apply failed: %v\n", err)
			os.Exit(1)
		}
	case "dm-encrypt":
		dmEnc := flag.NewFlagSet("dm-encrypt", flag.ExitOnError)
		stateDir := dmEnc.String("state-dir", "", "directory for participant state")
		plaintext := dmEnc.String("plaintext", "", "plaintext to encrypt")
		if err := dmEnc.Parse(os.Args[2:]); err != nil {
			fmt.Fprintf(os.Stderr, "failed to parse dm-encrypt flags: %v\n", err)
			os.Exit(2)
		}
		ct, err := runDMEncrypt(*stateDir, *plaintext)
		if err != nil {
			fmt.Fprintf(os.Stderr, "dm-encrypt failed: %v\n", err)
			os.Exit(1)
		}
		fmt.Println(ct)
	case "dm-decrypt":
		dmDec := flag.NewFlagSet("dm-decrypt", flag.ExitOnError)
		stateDir := dmDec.String("state-dir", "", "directory for participant state")
		ciphertext := dmDec.String("ciphertext", "", "base64-encoded MLSCiphertext")
		if err := dmDec.Parse(os.Args[2:]); err != nil {
			fmt.Fprintf(os.Stderr, "failed to parse dm-decrypt flags: %v\n", err)
			os.Exit(2)
		}
		pt, err := runDMDecrypt(*stateDir, *ciphertext)
		if err != nil {
			fmt.Fprintf(os.Stderr, "dm-decrypt failed: %v\n", err)
			os.Exit(1)
		}
		fmt.Println(pt)
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
	fmt.Fprintf(os.Stderr, "usage: mls-harness <smoke|vectors|soak|dm-*> [flags]\n")
	os.Exit(2)
}

func runDMKeyPackage(stateDir, name string, seed int64) (string, error) {
	if stateDir == "" {
		return "", errors.New("state-dir is required")
	}
	rng := deterministicRNGWithSeed(seed)
	restore := overrideCryptoRand(rng)
	defer restore()

	participant, err := loadParticipant(stateDir)
	if err != nil {
		return "", fmt.Errorf("load participant: %w", err)
	}
	if participant == nil {
		participant = &storedParticipant{Name: name, InitSecret: randomBytes(rng, 32)}
	}
	if len(participant.InitSecret) == 0 {
		participant.InitSecret = randomBytes(rng, 32)
	}
	if participant.Name == "" {
		participant.Name = name
	}

	_, kp, err := buildIdentityAndKeyPackage(participant.InitSecret, participant.Name)
	if err != nil {
		return "", fmt.Errorf("create keypackage: %w", err)
	}
	kpBytes, err := syntax.Marshal(*kp)
	if err != nil {
		return "", fmt.Errorf("marshal keypackage: %w", err)
	}
	if err := saveParticipant(stateDir, participant); err != nil {
		return "", fmt.Errorf("save participant: %w", err)
	}
	return base64.StdEncoding.EncodeToString(kpBytes), nil
}

func runDMInit(stateDir, peerKPBase64, groupIDBase64 string, seed int64) (string, string, error) {
	if stateDir == "" {
		return "", "", errors.New("state-dir is required")
	}
	if peerKPBase64 == "" {
		return "", "", errors.New("peer-keypackage is required")
	}
	groupID, err := base64.StdEncoding.DecodeString(groupIDBase64)
	if err != nil {
		return "", "", fmt.Errorf("decode group-id: %w", err)
	}

	participant, err := loadParticipant(stateDir)
	if err != nil {
		return "", "", fmt.Errorf("load participant: %w", err)
	}
	if participant == nil {
		return "", "", errors.New("participant state not initialized; run dm-keypackage first")
	}
	rng := deterministicRNGWithSeed(seed)
	restore := overrideCryptoRand(rng)
	defer restore()

	sigPriv, kp, err := buildIdentityAndKeyPackage(participant.InitSecret, participant.Name)
	if err != nil {
		return "", "", fmt.Errorf("build identity: %w", err)
	}

	peerKP, err := parseKeyPackage(peerKPBase64)
	if err != nil {
		return "", "", fmt.Errorf("parse peer keypackage: %w", err)
	}

	state, err := mls.NewEmptyState(groupID, participant.InitSecret, sigPriv, *kp)
	if err != nil {
		return "", "", fmt.Errorf("create group: %w", err)
	}

	add, err := state.Add(peerKP)
	if err != nil {
		return "", "", fmt.Errorf("add peer: %w", err)
	}
	if _, err := state.Handle(add); err != nil {
		return "", "", fmt.Errorf("handle add: %w", err)
	}

	commitSecret := randomBytes(rng, 32)
	commitPT, welcome, nextState, err := state.Commit(commitSecret)
	if err != nil {
		return "", "", fmt.Errorf("commit: %w", err)
	}

	commitBytes, err := syntax.Marshal(*commitPT)
	if err != nil {
		return "", "", fmt.Errorf("marshal commit: %w", err)
	}
	welcomeBytes, err := syntax.Marshal(*welcome)
	if err != nil {
		return "", "", fmt.Errorf("marshal welcome: %w", err)
	}

	participant.State = state
	participant.Pending = &pendingCommit{Commit: commitBytes, Welcome: welcomeBytes, NextState: nextState}

	if err := saveParticipant(stateDir, participant); err != nil {
		return "", "", fmt.Errorf("save participant: %w", err)
	}

	return base64.StdEncoding.EncodeToString(welcomeBytes), base64.StdEncoding.EncodeToString(commitBytes), nil
}

func runDMJoin(stateDir, welcomeBase64 string) error {
	if stateDir == "" {
		return errors.New("state-dir is required")
	}
	if welcomeBase64 == "" {
		return errors.New("welcome is required")
	}

	participant, err := loadParticipant(stateDir)
	if err != nil {
		return fmt.Errorf("load participant: %w", err)
	}
	if participant == nil {
		return errors.New("participant state not initialized; run dm-keypackage first")
	}

	welcomeBytes, err := base64.StdEncoding.DecodeString(welcomeBase64)
	if err != nil {
		return fmt.Errorf("decode welcome: %w", err)
	}
	var welcome mls.Welcome
	if _, err := syntax.Unmarshal(welcomeBytes, &welcome); err != nil {
		return fmt.Errorf("unmarshal welcome: %w", err)
	}

	sigPriv, kp, err := buildIdentityAndKeyPackage(participant.InitSecret, participant.Name)
	if err != nil {
		return fmt.Errorf("build identity: %w", err)
	}

	rng := deterministicRNG()
	restore := overrideCryptoRand(rng)
	defer restore()

	state, err := mls.NewJoinedState(participant.InitSecret, []mls.SignaturePrivateKey{sigPriv}, []mls.KeyPackage{*kp}, welcome)
	if err != nil {
		return fmt.Errorf("join state: %w", err)
	}

	participant.State = state
	participant.Pending = nil

	if err := saveParticipant(stateDir, participant); err != nil {
		return fmt.Errorf("save participant: %w", err)
	}
	return nil
}

func runDMCommitApply(stateDir, commitBase64 string) error {
	if stateDir == "" {
		return errors.New("state-dir is required")
	}
	if commitBase64 == "" {
		return errors.New("commit is required")
	}
	participant, err := loadParticipant(stateDir)
	if err != nil {
		return fmt.Errorf("load participant: %w", err)
	}
	if participant == nil || participant.State == nil {
		return errors.New("participant state not initialized")
	}

	commitBytes, err := base64.StdEncoding.DecodeString(commitBase64)
	if err != nil {
		return fmt.Errorf("decode commit: %w", err)
	}
	var commitPT mls.MLSPlaintext
	if _, err := syntax.Unmarshal(commitBytes, &commitPT); err != nil {
		return fmt.Errorf("unmarshal commit: %w", err)
	}

	if participant.Pending != nil {
		if !bytes.Equal(participant.Pending.Commit, commitBytes) {
			return errors.New("commit mismatch for pending apply")
		}
		if participant.Pending.NextState == nil {
			return errors.New("pending commit missing next state")
		}
		participant.State = participant.Pending.NextState
		participant.Pending = nil
	} else {
		nextState, err := participant.State.Handle(&commitPT)
		if err != nil {
			if strings.Contains(err.Error(), "epoch mismatch") && participant.State.Epoch == commitPT.Epoch+1 {
				if err := saveParticipant(stateDir, participant); err != nil {
					return fmt.Errorf("save participant: %w", err)
				}
				return nil
			}
			return fmt.Errorf("handle commit: %w", err)
		}
		participant.State = nextState
	}

	if err := saveParticipant(stateDir, participant); err != nil {
		return fmt.Errorf("save participant: %w", err)
	}
	return nil
}

func runDMEncrypt(stateDir, plaintext string) (string, error) {
	participant, err := loadParticipant(stateDir)
	if err != nil {
		return "", fmt.Errorf("load participant: %w", err)
	}
	if participant == nil || participant.State == nil {
		return "", errors.New("participant state not initialized")
	}
	ct, err := participant.State.Protect([]byte(plaintext))
	if err != nil {
		return "", fmt.Errorf("protect: %w", err)
	}
	ctBytes, err := syntax.Marshal(*ct)
	if err != nil {
		return "", fmt.Errorf("marshal ciphertext: %w", err)
	}
	if err := saveParticipant(stateDir, participant); err != nil {
		return "", fmt.Errorf("persist state: %w", err)
	}
	return base64.StdEncoding.EncodeToString(ctBytes), nil
}

func runDMDecrypt(stateDir, ciphertextBase64 string) (string, error) {
	participant, err := loadParticipant(stateDir)
	if err != nil {
		return "", fmt.Errorf("load participant: %w", err)
	}
	if participant == nil || participant.State == nil {
		return "", errors.New("participant state not initialized")
	}
	ctBytes, err := base64.StdEncoding.DecodeString(ciphertextBase64)
	if err != nil {
		return "", fmt.Errorf("decode ciphertext: %w", err)
	}
	var ct mls.MLSCiphertext
	if _, err := syntax.Unmarshal(ctBytes, &ct); err != nil {
		return "", fmt.Errorf("unmarshal ciphertext: %w", err)
	}
	pt, err := participant.State.Unprotect(&ct)
	if err != nil {
		return "", fmt.Errorf("unprotect: %w", err)
	}
	if err := saveParticipant(stateDir, participant); err != nil {
		return "", fmt.Errorf("persist state: %w", err)
	}
	return string(pt), nil
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

func participantPath(stateDir string) string {
	return filepath.Join(stateDir, "participant.gob")
}

func loadParticipant(stateDir string) (*storedParticipant, error) {
	primeGobRegistrations()
	path := participantPath(stateDir)
	data, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, nil
		}
		return nil, fmt.Errorf("read participant: %w", err)
	}

	var participant storedParticipant
	if err := gob.NewDecoder(bytes.NewReader(data)).Decode(&participant); err != nil {
		return nil, fmt.Errorf("decode participant: %w", err)
	}

	registerStateTypes(participant.State)
	if participant.Pending != nil {
		registerStateTypes(participant.Pending.NextState)
	}

	return &participant, nil
}

func saveParticipant(stateDir string, participant *storedParticipant) error {
	if participant == nil {
		return errors.New("nil participant")
	}
	if stateDir == "" {
		return errors.New("state-dir is required")
	}
	if err := os.MkdirAll(stateDir, 0o700); err != nil {
		return fmt.Errorf("create state-dir: %w", err)
	}

	registerStateTypes(participant.State)
	if participant.Pending != nil {
		registerStateTypes(participant.Pending.NextState)
		registerValue(participant.Pending)
	}

	var buf bytes.Buffer
	if err := gob.NewEncoder(&buf).Encode(participant); err != nil {
		return fmt.Errorf("encode participant: %w", err)
	}
	if err := os.WriteFile(participantPath(stateDir), buf.Bytes(), 0o600); err != nil {
		return fmt.Errorf("write participant: %w", err)
	}
	return nil
}

func primeGobRegistrations() {
	rng := deterministicRNG()
	restore := overrideCryptoRand(rng)
	defer restore()

	secret := randomBytes(rng, 32)
	sigPriv, kp, err := buildIdentityAndKeyPackage(secret, "prime")
	if err != nil {
		return
	}
	state, err := mls.NewEmptyState([]byte{0xAA}, secret, sigPriv, *kp)
	if err != nil {
		return
	}
	registerStateTypes(state)
}

func buildIdentityAndKeyPackage(secret []byte, name string) (mls.SignaturePrivateKey, *mls.KeyPackage, error) {
	if len(secret) == 0 {
		return mls.SignaturePrivateKey{}, nil, errors.New("init secret required")
	}
	suite := mls.X25519_AES128GCM_SHA256_Ed25519
	scheme := suite.Scheme()
	sigPriv, err := scheme.Derive(secret)
	if err != nil {
		return mls.SignaturePrivateKey{}, nil, fmt.Errorf("derive identity key: %w", err)
	}
	cred := mls.NewBasicCredential([]byte(name), scheme, sigPriv.PublicKey)
	kp, err := mls.NewKeyPackageWithSecret(suite, secret, cred, sigPriv)
	if err != nil {
		return mls.SignaturePrivateKey{}, nil, fmt.Errorf("create key package: %w", err)
	}
	if err := makeKeyPackageDeterministic(kp, sigPriv); err != nil {
		return mls.SignaturePrivateKey{}, nil, fmt.Errorf("stabilize key package: %w", err)
	}
	return sigPriv, kp, nil
}

func parseKeyPackage(b64 string) (mls.KeyPackage, error) {
	data, err := base64.StdEncoding.DecodeString(b64)
	if err != nil {
		return mls.KeyPackage{}, fmt.Errorf("decode keypackage: %w", err)
	}
	var kp mls.KeyPackage
	if _, err := syntax.Unmarshal(data, &kp); err != nil {
		return mls.KeyPackage{}, fmt.Errorf("unmarshal keypackage: %w", err)
	}
	return kp, nil
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
	gob.Register(&mls.MLSPlaintext{})
	gob.Register(&mls.Welcome{})
	gob.Register(&pendingCommit{})
	gob.Register(&storedParticipant{})
}

func deterministicRNG() *rand.Rand {
	rand.Seed(42)
	return rand.New(rand.NewSource(1337))
}

func deterministicRNGWithSeed(seed int64) *rand.Rand {
	return rand.New(rand.NewSource(seed))
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
