package harness

import (
	"bytes"
	crand "crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"hash"
	"math/rand"

	mls "github.com/cisco/go-mls"
	syntax "github.com/cisco/go-tls-syntax"
)

type Participant struct {
	Name        string
	InitSecret  []byte
	IdentityKey mls.SignaturePrivateKey
	KeyPackage  mls.KeyPackage
	State       *mls.State
}

func RandomBytes(rng *rand.Rand, n int) []byte {
	b := make([]byte, n)
	if _, err := rng.Read(b); err != nil {
		panic(err)
	}
	return b
}

func DeterministicRNG() *rand.Rand {
	rand.Seed(42)
	return rand.New(rand.NewSource(1337))
}

func DeterministicRNGWithSeed(seed int64) *rand.Rand {
	return rand.New(rand.NewSource(seed))
}

func OverrideCryptoRand(rng *rand.Rand) func() {
	original := crand.Reader
	crand.Reader = rng
	return func() {
		crand.Reader = original
	}
}

func MakeKeyPackageDeterministic(kp *mls.KeyPackage, sigPriv mls.SignaturePrivateKey) error {
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

func NewParticipant(rng *rand.Rand, suite mls.CipherSuite, name string) (*Participant, error) {
	secret := RandomBytes(rng, 32)
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

	if err := MakeKeyPackageDeterministic(kp, sigPriv); err != nil {
		return nil, fmt.Errorf("stabilize key package: %w", err)
	}

	return &Participant{
		Name:        name,
		InitSecret:  secret,
		IdentityKey: sigPriv,
		KeyPackage:  *kp,
	}, nil
}

func BootstrapPairWithDigest(rng *rand.Rand, dig *TranscriptDigest) (*Participant, *Participant, error) {
	suite := mls.X25519_AES128GCM_SHA256_Ed25519

	alice, err := NewParticipant(rng, suite, "alice")
	if err != nil {
		return nil, nil, fmt.Errorf("alice init: %w", err)
	}
	bob, err := NewParticipant(rng, suite, "bob")
	if err != nil {
		return nil, nil, fmt.Errorf("bob init: %w", err)
	}

	groupID := []byte{0x01, 0x02, 0x03, 0x04}
	if dig != nil {
		if err := dig.AddBytes("group-id", groupID); err != nil {
			return nil, nil, fmt.Errorf("digest group id: %w", err)
		}
		if err := dig.AddKeyPackage("alice-key-package", alice.KeyPackage); err != nil {
			return nil, nil, fmt.Errorf("digest alice key package: %w", err)
		}
		if err := dig.AddKeyPackage("bob-key-package", bob.KeyPackage); err != nil {
			return nil, nil, fmt.Errorf("digest bob key package: %w", err)
		}
	}

	alice.State, err = mls.NewEmptyState(groupID, alice.InitSecret, alice.IdentityKey, alice.KeyPackage)
	if err != nil {
		return nil, nil, fmt.Errorf("create group: %w", err)
	}

	add, err := alice.State.Add(bob.KeyPackage)
	if err != nil {
		return nil, nil, fmt.Errorf("add bob: %w", err)
	}
	if dig != nil {
		if err := dig.AddMLSPlaintext("add", add); err != nil {
			return nil, nil, fmt.Errorf("digest add: %w", err)
		}
	}
	if _, err = alice.State.Handle(add); err != nil {
		return nil, nil, fmt.Errorf("handle add: %w", err)
	}

	commitSecret := RandomBytes(rng, 32)
	commitPT, welcome, nextAlice, err := alice.State.Commit(commitSecret)
	if err != nil {
		return nil, nil, fmt.Errorf("commit: %w", err)
	}
	if dig != nil {
		if err := dig.AddMLSPlaintext("commit", commitPT); err != nil {
			return nil, nil, fmt.Errorf("digest commit: %w", err)
		}
		if err := dig.AddWelcome("welcome", welcome); err != nil {
			return nil, nil, fmt.Errorf("digest welcome: %w", err)
		}
	}
	alice.State = nextAlice

	bob.State, err = mls.NewJoinedState(bob.InitSecret, []mls.SignaturePrivateKey{bob.IdentityKey}, []mls.KeyPackage{bob.KeyPackage}, *welcome)
	if err != nil {
		return nil, nil, fmt.Errorf("bob join: %w", err)
	}

	return alice, bob, nil
}

func ExchangeOnce(sender, receiver *Participant, msg []byte) error {
	return ExchangeOnceWithDigest(sender, receiver, msg, "", nil)
}

func ExchangeOnceWithDigest(sender, receiver *Participant, msg []byte, label string, dig *TranscriptDigest) error {
	ct, err := sender.State.Protect(msg)
	if err != nil {
		return fmt.Errorf("protect failed for %s: %w", sender.Name, err)
	}

	if dig != nil {
		if err := dig.AddCiphertext(label, ct); err != nil {
			return fmt.Errorf("digest update failed: %w", err)
		}
	}

	pt, err := receiver.State.Unprotect(ct)
	if err != nil {
		return fmt.Errorf("unprotect failed for %s: %w", receiver.Name, err)
	}

	if !bytes.Equal(pt, msg) {
		return fmt.Errorf("plaintext mismatch for %s -> %s", sender.Name, receiver.Name)
	}

	return nil
}

type TranscriptDigest struct {
	h hash.Hash
}

func NewTranscriptDigest() *TranscriptDigest {
	return &TranscriptDigest{h: sha256.New()}
}

func (t *TranscriptDigest) AddBytes(label string, data []byte) error {
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

func (t *TranscriptDigest) AddKeyPackage(label string, kp mls.KeyPackage) error {
	if t == nil {
		return nil
	}
	data, err := syntax.Marshal(kp)
	if err != nil {
		return err
	}
	return t.AddBytes(label, data)
}

func (t *TranscriptDigest) AddMLSPlaintext(label string, pt *mls.MLSPlaintext) error {
	if pt == nil {
		return fmt.Errorf("nil MLSPlaintext for label %s", label)
	}
	data, err := syntax.Marshal(pt)
	if err != nil {
		return err
	}
	return t.AddBytes(label, data)
}

func (t *TranscriptDigest) AddWelcome(label string, welcome *mls.Welcome) error {
	if welcome == nil {
		return fmt.Errorf("nil welcome for label %s", label)
	}
	data, err := syntax.Marshal(*welcome)
	if err != nil {
		return err
	}
	return t.AddBytes(label, data)
}

func (t *TranscriptDigest) AddCiphertext(label string, ct *mls.MLSCiphertext) error {
	if ct == nil {
		return fmt.Errorf("nil ciphertext for label %s", label)
	}
	data, err := syntax.Marshal(*ct)
	if err != nil {
		return err
	}
	return t.AddBytes(label, data)
}

func (t *TranscriptDigest) HexSum() string {
	if t == nil {
		return ""
	}
	return hex.EncodeToString(t.h.Sum(nil))
}
