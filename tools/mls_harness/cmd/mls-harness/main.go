package main

import (
	"bytes"
	"encoding/gob"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"

	mls "github.com/cisco/go-mls"

	"github.com/polycentric/fictional-octo-umbrella/tools/mls_harness/internal/dm"
	"github.com/polycentric/fictional-octo-umbrella/tools/mls_harness/internal/harness"
)

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
	case "wg-vectors":
		wgVectors := flag.NewFlagSet("wg-vectors", flag.ExitOnError)
		dir := wgVectors.String("vectors-dir", defaultWGVectorsDir, "directory containing MLSWG JSON vectors")
		maxBytes := wgVectors.Int64("max-bytes", defaultWGMaxBytes, "maximum size per vector file in bytes")
		if err := wgVectors.Parse(os.Args[2:]); err != nil {
			fmt.Fprintf(os.Stderr, "failed to parse wg-vectors flags: %v\n", err)
			os.Exit(2)
		}

		if err := runWGVectors(*dir, *maxBytes); err != nil {
			fmt.Fprintf(os.Stderr, "wg-vectors failed: %v\n", err)
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
	fmt.Fprintf(os.Stderr, "usage: mls-harness <smoke|vectors|wg-vectors|soak|dm-*> [flags]\n")
	os.Exit(2)
}

func runDMKeyPackage(stateDir, name string, seed int64) (string, error) {
	if stateDir == "" {
		return "", errors.New("state-dir is required")
	}
	participantBlob, err := loadParticipantBlob(stateDir)
	if err != nil {
		return "", fmt.Errorf("load participant: %w", err)
	}
	participantBlob, kp, err := dm.KeyPackage(participantBlob, name, seed)
	if err != nil {
		return "", err
	}
	if err := saveParticipantBlob(stateDir, participantBlob); err != nil {
		return "", fmt.Errorf("save participant: %w", err)
	}
	return kp, nil
}

func runDMInit(stateDir, peerKPBase64, groupIDBase64 string, seed int64) (string, string, error) {
	if stateDir == "" {
		return "", "", errors.New("state-dir is required")
	}
	participantBlob, err := loadParticipantBlob(stateDir)
	if err != nil {
		return "", "", fmt.Errorf("load participant: %w", err)
	}
	if participantBlob == "" {
		return "", "", errors.New("participant state not initialized; run dm-keypackage first")
	}
	participantBlob, welcome, commit, err := dm.Init(participantBlob, peerKPBase64, groupIDBase64, seed)
	if err != nil {
		return "", "", err
	}
	if err := saveParticipantBlob(stateDir, participantBlob); err != nil {
		return "", "", fmt.Errorf("save participant: %w", err)
	}
	return welcome, commit, nil
}

func runDMJoin(stateDir, welcomeBase64 string) error {
	if stateDir == "" {
		return errors.New("state-dir is required")
	}
	if welcomeBase64 == "" {
		return errors.New("welcome is required")
	}

	participantBlob, err := loadParticipantBlob(stateDir)
	if err != nil {
		return fmt.Errorf("load participant: %w", err)
	}
	if participantBlob == "" {
		return errors.New("participant state not initialized; run dm-keypackage first")
	}
	participantBlob, err = dm.Join(participantBlob, welcomeBase64)
	if err != nil {
		return err
	}
	if err := saveParticipantBlob(stateDir, participantBlob); err != nil {
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
	participantBlob, err := loadParticipantBlob(stateDir)
	if err != nil {
		return fmt.Errorf("load participant: %w", err)
	}
	if participantBlob == "" {
		return errors.New("participant state not initialized")
	}
	participantBlob, _, err = dm.CommitApply(participantBlob, commitBase64)
	if err != nil {
		return err
	}
	if err := saveParticipantBlob(stateDir, participantBlob); err != nil {
		return fmt.Errorf("save participant: %w", err)
	}
	return nil
}

func runDMEncrypt(stateDir, plaintext string) (string, error) {
	participantBlob, err := loadParticipantBlob(stateDir)
	if err != nil {
		return "", fmt.Errorf("load participant: %w", err)
	}
	if participantBlob == "" {
		return "", errors.New("participant state not initialized")
	}
	participantBlob, ciphertext, err := dm.Encrypt(participantBlob, plaintext)
	if err != nil {
		return "", err
	}
	if err := saveParticipantBlob(stateDir, participantBlob); err != nil {
		return "", fmt.Errorf("persist state: %w", err)
	}
	return ciphertext, nil
}

func runDMDecrypt(stateDir, ciphertextBase64 string) (string, error) {
	participantBlob, err := loadParticipantBlob(stateDir)
	if err != nil {
		return "", fmt.Errorf("load participant: %w", err)
	}
	if participantBlob == "" {
		return "", errors.New("participant state not initialized")
	}
	participantBlob, plaintext, err := dm.Decrypt(participantBlob, ciphertextBase64)
	if err != nil {
		return "", err
	}
	if err := saveParticipantBlob(stateDir, participantBlob); err != nil {
		return "", fmt.Errorf("persist state: %w", err)
	}
	return plaintext, nil
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

	rng := harness.DeterministicRNG()
	restore := harness.OverrideCryptoRand(rng)
	defer restore()

	alice, bob, err := harness.BootstrapPairWithDigest(rng, nil)
	if err != nil {
		return fmt.Errorf("failed to bootstrap participants: %w", err)
	}

	for i := 0; i < iterations; i++ {
		payload := []byte(fmt.Sprintf("msg-%d", i))

		if err := harness.ExchangeOnceWithDigest(alice, bob, payload, "", nil); err != nil {
			return fmt.Errorf("iteration %d alice->bob: %w", i, err)
		}

		if err := harness.ExchangeOnceWithDigest(bob, alice, payload, "", nil); err != nil {
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

func runVectors(vectorPath string) error {
	if vectorPath == "" {
		return errors.New("vector-file is required")
	}

	result, err := harness.VerifyVectorFile(vectorPath)
	if err != nil {
		return err
	}

	if !result.OK {
		return fmt.Errorf("digest mismatch: computed %s expected %s", result.Digest, result.ExpectedDigest)
	}

	fmt.Println("ok")
	return nil
}

func persistRoundTrip(stateDir string, alice, bob *harness.Participant) error {
	if err := saveState(filepath.Join(stateDir, "alice.gob"), alice.State); err != nil {
		return fmt.Errorf("alice persist: %w", err)
	}
	if err := saveState(filepath.Join(stateDir, "bob.gob"), bob.State); err != nil {
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

	alice.State = restoredAlice
	bob.State = restoredBob
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

func loadParticipantBlob(stateDir string) (string, error) {
	path := participantPath(stateDir)
	data, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return "", nil
		}
		return "", fmt.Errorf("read participant: %w", err)
	}
	return string(bytes.TrimSpace(data)), nil
}

func saveParticipantBlob(stateDir, participantBlob string) error {
	if stateDir == "" {
		return errors.New("state-dir is required")
	}
	if err := os.MkdirAll(stateDir, 0o700); err != nil {
		return fmt.Errorf("create state-dir: %w", err)
	}
	if err := os.WriteFile(participantPath(stateDir), []byte(participantBlob), 0o600); err != nil {
		return fmt.Errorf("write participant: %w", err)
	}
	return nil
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
