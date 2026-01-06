package harness

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"

	mls "github.com/cisco/go-mls"
)

type VectorSpec struct {
	Name       string `json:"name"`
	Suite      string `json:"cipher_suite"`
	Iterations int    `json:"iterations"`
	DigestHex  string `json:"digest_sha256_hex"`
}

type VerifyResult struct {
	Digest         string
	ExpectedDigest string
	OK             bool
}

func LoadVectorSpec(path string) (*VectorSpec, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read vector file: %w", err)
	}

	return LoadVectorSpecFromJSON(data)
}

func LoadVectorSpecFromJSON(data []byte) (*VectorSpec, error) {
	var spec VectorSpec
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

func VerifyVectorFile(vectorPath string) (*VerifyResult, error) {
	spec, err := LoadVectorSpec(vectorPath)
	if err != nil {
		return nil, fmt.Errorf("load vector spec: %w", err)
	}

	return VerifyVectorSpec(spec)
}

func VerifyVectorJSON(data []byte) (*VerifyResult, error) {
	spec, err := LoadVectorSpecFromJSON(data)
	if err != nil {
		return nil, err
	}

	return VerifyVectorSpec(spec)
}

func VerifyVectorSpec(spec *VectorSpec) (*VerifyResult, error) {
	if spec == nil {
		return nil, errors.New("vector spec is required")
	}

	rng := DeterministicRNG()
	restore := OverrideCryptoRand(rng)
	defer restore()
	dig := NewTranscriptDigest()

	alice, bob, err := BootstrapPairWithDigest(rng, dig)
	if err != nil {
		return nil, fmt.Errorf("failed to bootstrap participants: %w", err)
	}

	for i := 0; i < spec.Iterations; i++ {
		payload := []byte(fmt.Sprintf("msg-%d", i))

		aliceLabel := fmt.Sprintf("iter-%d-%s-%s", i, alice.Name, bob.Name)
		if err := ExchangeOnceWithDigest(alice, bob, payload, aliceLabel, dig); err != nil {
			return &VerifyResult{Digest: dig.HexSum(), ExpectedDigest: strings.ToLower(spec.DigestHex)}, fmt.Errorf("iteration %d alice->bob: %w", i, err)
		}

		bobLabel := fmt.Sprintf("iter-%d-%s-%s", i, bob.Name, alice.Name)
		if err := ExchangeOnceWithDigest(bob, alice, payload, bobLabel, dig); err != nil {
			return &VerifyResult{Digest: dig.HexSum(), ExpectedDigest: strings.ToLower(spec.DigestHex)}, fmt.Errorf("iteration %d bob->alice: %w", i, err)
		}
	}

	computed := dig.HexSum()
	expected := strings.ToLower(spec.DigestHex)
	if computed != expected {
		return &VerifyResult{Digest: computed, ExpectedDigest: expected}, fmt.Errorf("digest mismatch: computed %s expected %s", computed, expected)
	}

	return &VerifyResult{Digest: computed, ExpectedDigest: expected, OK: true}, nil
}
