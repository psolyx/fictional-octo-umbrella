package main

import (
	"bytes"
	"encoding/gob"
	"errors"
	"flag"
	"fmt"
	"math/rand"
	"os"
	"path/filepath"

	mls "github.com/cisco/go-mls"
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
	default:
		usage()
	}
}

func usage() {
	fmt.Fprintf(os.Stderr, "usage: mls-harness smoke --iterations N --save-every K --state-dir PATH\n")
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

	rand.Seed(42)
	rng := rand.New(rand.NewSource(1337))

	alice, bob, err := bootstrapPair(rng)
	if err != nil {
		return fmt.Errorf("failed to bootstrap participants: %w", err)
	}

	for i := 0; i < iterations; i++ {
		payload := []byte(fmt.Sprintf("msg-%d", i))

		if err := exchangeOnce(alice, bob, payload); err != nil {
			return fmt.Errorf("iteration %d alice->bob: %w", i, err)
		}

		if err := exchangeOnce(bob, alice, payload); err != nil {
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

func exchangeOnce(sender, receiver *participant, msg []byte) error {
	ct, err := sender.state.Protect(msg)
	if err != nil {
		return fmt.Errorf("protect failed for %s: %w", sender.name, err)
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
	alice.state, err = mls.NewEmptyState(groupID, alice.initSecret, alice.identityKey, alice.keyPackage)
	if err != nil {
		return nil, nil, fmt.Errorf("create group: %w", err)
	}

	add, err := alice.state.Add(bob.keyPackage)
	if err != nil {
		return nil, nil, fmt.Errorf("add bob: %w", err)
	}
	if _, err = alice.state.Handle(add); err != nil {
		return nil, nil, fmt.Errorf("handle add: %w", err)
	}

	commitSecret := randomBytes(rng, 32)
	_, welcome, nextAlice, err := alice.state.Commit(commitSecret)
	if err != nil {
		return nil, nil, fmt.Errorf("commit: %w", err)
	}
	alice.state = nextAlice

	bob.state, err = mls.NewJoinedState(bob.initSecret, []mls.SignaturePrivateKey{bob.identityKey}, []mls.KeyPackage{bob.keyPackage}, *welcome)
	if err != nil {
		return nil, nil, fmt.Errorf("bob join: %w", err)
	}

	return alice, bob, nil
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
