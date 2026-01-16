package dm

import (
	"bytes"
	"encoding/base64"
	"encoding/gob"
	"errors"
	"fmt"
	"strings"

	mls "github.com/cisco/go-mls"
	syntax "github.com/cisco/go-tls-syntax"

	"github.com/polycentric/fictional-octo-umbrella/tools/mls_harness/internal/harness"
)

type Participant struct {
	Name       string
	InitSecret []byte
	State      *mls.State
	Pending    *PendingCommit
}

type PendingCommit struct {
	Commit    []byte
	Welcome   []byte
	NextState *mls.State
}

func init() {
	gob.Register(&mls.State{})
	gob.Register(&mls.MLSPlaintext{})
	gob.Register(&mls.Welcome{})
	gob.Register(&PendingCommit{})
	gob.Register(&Participant{})
	prime_gob_registrations()
}

func KeyPackage(participant_b64, name string, seed int64) (string, string, error) {
	if name == "" {
		return "", "", errors.New("participant name is required")
	}
	rng := harness.DeterministicRNGWithSeed(seed)
	restore := harness.OverrideCryptoRand(rng)
	defer restore()

	participant, err := decode_participant(participant_b64)
	if err != nil {
		return "", "", fmt.Errorf("decode participant: %w", err)
	}
	if participant == nil {
		participant = &Participant{Name: name, InitSecret: harness.RandomBytes(rng, 32)}
	}
	if len(participant.InitSecret) == 0 {
		participant.InitSecret = harness.RandomBytes(rng, 32)
	}
	if participant.Name == "" {
		participant.Name = name
	}

	_, kp, err := build_identity_and_keypackage(participant.InitSecret, participant.Name)
	if err != nil {
		return "", "", fmt.Errorf("create keypackage: %w", err)
	}
	kp_bytes, err := syntax.Marshal(*kp)
	if err != nil {
		return "", "", fmt.Errorf("marshal keypackage: %w", err)
	}

	participant_b64, err = encode_participant(participant)
	if err != nil {
		return "", "", fmt.Errorf("encode participant: %w", err)
	}

	return participant_b64, base64.StdEncoding.EncodeToString(kp_bytes), nil
}

func Init(participant_b64, peer_kp_b64, group_id_b64 string, seed int64) (string, string, string, error) {
	if participant_b64 == "" {
		return "", "", "", errors.New("participant is required")
	}
	if peer_kp_b64 == "" {
		return "", "", "", errors.New("peer keypackage is required")
	}
	return initWithPeers(participant_b64, []string{peer_kp_b64}, group_id_b64, seed)
}

func InitMany(participant_b64 string, peer_kps_b64 []string, group_id_b64 string, seed int64) (string, string, string, error) {
	if participant_b64 == "" {
		return "", "", "", errors.New("participant is required")
	}
	if err := validatePeerKeyPackages(peer_kps_b64, 2); err != nil {
		return "", "", "", err
	}
	return initWithPeers(participant_b64, peer_kps_b64, group_id_b64, seed)
}

func AddMany(participant_b64 string, peer_kps_b64 []string, seed int64) (string, string, string, error) {
	if participant_b64 == "" {
		return "", "", "", errors.New("participant is required")
	}
	if err := validatePeerKeyPackages(peer_kps_b64, 1); err != nil {
		return "", "", "", err
	}

	participant, err := decode_participant(participant_b64)
	if err != nil {
		return "", "", "", fmt.Errorf("decode participant: %w", err)
	}
	if participant == nil || participant.State == nil {
		return "", "", "", errors.New("participant state not initialized")
	}

	rng := harness.DeterministicRNGWithSeed(seed)
	restore := harness.OverrideCryptoRand(rng)
	defer restore()

	for _, peer_kp_b64 := range peer_kps_b64 {
		peer_kp, err := parse_keypackage(peer_kp_b64)
		if err != nil {
			return "", "", "", fmt.Errorf("parse peer keypackage: %w", err)
		}

		add, err := participant.State.Add(peer_kp)
		if err != nil {
			return "", "", "", fmt.Errorf("add peer: %w", err)
		}
		if _, err := participant.State.Handle(add); err != nil {
			return "", "", "", fmt.Errorf("handle add: %w", err)
		}
	}

	commit_secret := harness.RandomBytes(rng, 32)
	commit_pt, welcome, next_state, err := participant.State.Commit(commit_secret)
	if err != nil {
		return "", "", "", fmt.Errorf("commit: %w", err)
	}

	commit_bytes, err := syntax.Marshal(*commit_pt)
	if err != nil {
		return "", "", "", fmt.Errorf("marshal commit: %w", err)
	}
	welcome_bytes, err := syntax.Marshal(*welcome)
	if err != nil {
		return "", "", "", fmt.Errorf("marshal welcome: %w", err)
	}

	participant.Pending = &PendingCommit{Commit: commit_bytes, Welcome: welcome_bytes, NextState: next_state}

	participant_b64, err = encode_participant(participant)
	if err != nil {
		return "", "", "", fmt.Errorf("encode participant: %w", err)
	}

	return participant_b64, base64.StdEncoding.EncodeToString(welcome_bytes), base64.StdEncoding.EncodeToString(commit_bytes), nil
}

func initWithPeers(participant_b64 string, peer_kps_b64 []string, group_id_b64 string, seed int64) (string, string, string, error) {
	group_id, err := base64.StdEncoding.DecodeString(group_id_b64)
	if err != nil {
		return "", "", "", fmt.Errorf("decode group-id: %w", err)
	}

	participant, err := decode_participant(participant_b64)
	if err != nil {
		return "", "", "", fmt.Errorf("decode participant: %w", err)
	}
	if participant == nil {
		return "", "", "", errors.New("participant state not initialized")
	}
	rng := harness.DeterministicRNGWithSeed(seed)
	restore := harness.OverrideCryptoRand(rng)
	defer restore()

	sig_priv, kp, err := build_identity_and_keypackage(participant.InitSecret, participant.Name)
	if err != nil {
		return "", "", "", fmt.Errorf("build identity: %w", err)
	}

	state, err := mls.NewEmptyState(group_id, participant.InitSecret, sig_priv, *kp)
	if err != nil {
		return "", "", "", fmt.Errorf("create group: %w", err)
	}

	for _, peer_kp_b64 := range peer_kps_b64 {
		peer_kp, err := parse_keypackage(peer_kp_b64)
		if err != nil {
			return "", "", "", fmt.Errorf("parse peer keypackage: %w", err)
		}

		add, err := state.Add(peer_kp)
		if err != nil {
			return "", "", "", fmt.Errorf("add peer: %w", err)
		}
		if _, err := state.Handle(add); err != nil {
			return "", "", "", fmt.Errorf("handle add: %w", err)
		}
	}

	commit_secret := harness.RandomBytes(rng, 32)
	commit_pt, welcome, next_state, err := state.Commit(commit_secret)
	if err != nil {
		return "", "", "", fmt.Errorf("commit: %w", err)
	}

	commit_bytes, err := syntax.Marshal(*commit_pt)
	if err != nil {
		return "", "", "", fmt.Errorf("marshal commit: %w", err)
	}
	welcome_bytes, err := syntax.Marshal(*welcome)
	if err != nil {
		return "", "", "", fmt.Errorf("marshal welcome: %w", err)
	}

	participant.State = state
	participant.Pending = &PendingCommit{Commit: commit_bytes, Welcome: welcome_bytes, NextState: next_state}

	participant_b64, err = encode_participant(participant)
	if err != nil {
		return "", "", "", fmt.Errorf("encode participant: %w", err)
	}

	return participant_b64, base64.StdEncoding.EncodeToString(welcome_bytes), base64.StdEncoding.EncodeToString(commit_bytes), nil
}

func validatePeerKeyPackages(peer_kps_b64 []string, minCount int) error {
	if len(peer_kps_b64) < minCount {
		if minCount == 1 {
			return errors.New("at least one peer keypackage is required")
		}
		return errors.New("at least two peer keypackages are required")
	}
	for _, peer_kp_b64 := range peer_kps_b64 {
		if peer_kp_b64 == "" {
			return errors.New("peer keypackage is required")
		}
	}
	return nil
}

func Join(participant_b64, welcome_b64 string) (string, error) {
	if participant_b64 == "" {
		return "", errors.New("participant is required")
	}
	if welcome_b64 == "" {
		return "", errors.New("welcome is required")
	}

	participant, err := decode_participant(participant_b64)
	if err != nil {
		return "", fmt.Errorf("decode participant: %w", err)
	}
	if participant == nil {
		return "", errors.New("participant state not initialized")
	}

	welcome_bytes, err := base64.StdEncoding.DecodeString(welcome_b64)
	if err != nil {
		return "", fmt.Errorf("decode welcome: %w", err)
	}
	var welcome mls.Welcome
	if _, err := syntax.Unmarshal(welcome_bytes, &welcome); err != nil {
		return "", fmt.Errorf("unmarshal welcome: %w", err)
	}

	sig_priv, kp, err := build_identity_and_keypackage(participant.InitSecret, participant.Name)
	if err != nil {
		return "", fmt.Errorf("build identity: %w", err)
	}

	rng := harness.DeterministicRNG()
	restore := harness.OverrideCryptoRand(rng)
	defer restore()

	state, err := mls.NewJoinedState(participant.InitSecret, []mls.SignaturePrivateKey{sig_priv}, []mls.KeyPackage{*kp}, welcome)
	if err != nil {
		return "", fmt.Errorf("join state: %w", err)
	}

	participant.State = state
	participant.Pending = nil

	participant_b64, err = encode_participant(participant)
	if err != nil {
		return "", fmt.Errorf("encode participant: %w", err)
	}

	return participant_b64, nil
}

func CommitApply(participant_b64, commit_b64 string) (string, bool, error) {
	if participant_b64 == "" {
		return "", false, errors.New("participant is required")
	}
	if commit_b64 == "" {
		return "", false, errors.New("commit is required")
	}

	participant, err := decode_participant(participant_b64)
	if err != nil {
		return "", false, fmt.Errorf("decode participant: %w", err)
	}
	if participant == nil || participant.State == nil {
		return "", false, errors.New("participant state not initialized")
	}

	commit_bytes, err := base64.StdEncoding.DecodeString(commit_b64)
	if err != nil {
		return "", false, fmt.Errorf("decode commit: %w", err)
	}
	var commit_pt mls.MLSPlaintext
	if _, err := syntax.Unmarshal(commit_bytes, &commit_pt); err != nil {
		return "", false, fmt.Errorf("unmarshal commit: %w", err)
	}

	noop := false
	if participant.Pending != nil {
		if !bytes.Equal(participant.Pending.Commit, commit_bytes) {
			return "", false, errors.New("commit mismatch for pending apply")
		}
		if participant.Pending.NextState == nil {
			return "", false, errors.New("pending commit missing next state")
		}
		participant.State = participant.Pending.NextState
		participant.Pending = nil
	} else {
		next_state, err := participant.State.Handle(&commit_pt)
		if err != nil {
			if strings.Contains(err.Error(), "epoch mismatch") && participant.State.Epoch == commit_pt.Epoch+1 {
				noop = true
			} else {
				return "", false, fmt.Errorf("handle commit: %w", err)
			}
		} else {
			participant.State = next_state
		}
	}

	participant_b64, err = encode_participant(participant)
	if err != nil {
		return "", noop, fmt.Errorf("encode participant: %w", err)
	}

	return participant_b64, noop, nil
}

func Encrypt(participant_b64, plaintext string) (string, string, error) {
	if participant_b64 == "" {
		return "", "", errors.New("participant is required")
	}
	participant, err := decode_participant(participant_b64)
	if err != nil {
		return "", "", fmt.Errorf("decode participant: %w", err)
	}
	if participant == nil || participant.State == nil {
		return "", "", errors.New("participant state not initialized")
	}
	ct, err := participant.State.Protect([]byte(plaintext))
	if err != nil {
		return "", "", fmt.Errorf("protect: %w", err)
	}
	ct_bytes, err := syntax.Marshal(*ct)
	if err != nil {
		return "", "", fmt.Errorf("marshal ciphertext: %w", err)
	}
	participant_b64, err = encode_participant(participant)
	if err != nil {
		return "", "", fmt.Errorf("encode participant: %w", err)
	}
	return participant_b64, base64.StdEncoding.EncodeToString(ct_bytes), nil
}

func Decrypt(participant_b64, ciphertext_b64 string) (string, string, error) {
	if participant_b64 == "" {
		return "", "", errors.New("participant is required")
	}
	participant, err := decode_participant(participant_b64)
	if err != nil {
		return "", "", fmt.Errorf("decode participant: %w", err)
	}
	if participant == nil || participant.State == nil {
		return "", "", errors.New("participant state not initialized")
	}
	ct_bytes, err := base64.StdEncoding.DecodeString(ciphertext_b64)
	if err != nil {
		return "", "", fmt.Errorf("decode ciphertext: %w", err)
	}
	var ct mls.MLSCiphertext
	if _, err := syntax.Unmarshal(ct_bytes, &ct); err != nil {
		return "", "", fmt.Errorf("unmarshal ciphertext: %w", err)
	}
	pt, err := participant.State.Unprotect(&ct)
	if err != nil {
		return "", "", fmt.Errorf("unprotect: %w", err)
	}
	participant_b64, err = encode_participant(participant)
	if err != nil {
		return "", "", fmt.Errorf("encode participant: %w", err)
	}
	return participant_b64, string(pt), nil
}

func decode_participant(participant_b64 string) (*Participant, error) {
	if participant_b64 == "" {
		return nil, nil
	}
	data, err := base64.StdEncoding.DecodeString(participant_b64)
	if err != nil {
		return nil, fmt.Errorf("decode base64: %w", err)
	}
	var participant Participant
	if err := gob.NewDecoder(bytes.NewReader(data)).Decode(&participant); err != nil {
		return nil, fmt.Errorf("decode gob: %w", err)
	}

	register_state_types(participant.State)
	if participant.Pending != nil {
		register_state_types(participant.Pending.NextState)
	}

	return &participant, nil
}

func encode_participant(participant *Participant) (string, error) {
	if participant == nil {
		return "", errors.New("nil participant")
	}
	register_state_types(participant.State)
	if participant.Pending != nil {
		register_state_types(participant.Pending.NextState)
		register_value(participant.Pending)
	}

	var buf bytes.Buffer
	if err := gob.NewEncoder(&buf).Encode(participant); err != nil {
		return "", fmt.Errorf("encode participant: %w", err)
	}
	return base64.StdEncoding.EncodeToString(buf.Bytes()), nil
}

func prime_gob_registrations() {
	rng := harness.DeterministicRNG()
	restore := harness.OverrideCryptoRand(rng)
	defer restore()

	secret := harness.RandomBytes(rng, 32)
	sig_priv, kp, err := build_identity_and_keypackage(secret, "prime")
	if err != nil {
		return
	}
	state, err := mls.NewEmptyState([]byte{0xAA}, secret, sig_priv, *kp)
	if err != nil {
		return
	}
	register_state_types(state)
}

func build_identity_and_keypackage(secret []byte, name string) (mls.SignaturePrivateKey, *mls.KeyPackage, error) {
	if len(secret) == 0 {
		return mls.SignaturePrivateKey{}, nil, errors.New("init secret required")
	}
	suite := mls.X25519_AES128GCM_SHA256_Ed25519
	scheme := suite.Scheme()
	sig_priv, err := scheme.Derive(secret)
	if err != nil {
		return mls.SignaturePrivateKey{}, nil, fmt.Errorf("derive identity key: %w", err)
	}
	cred := mls.NewBasicCredential([]byte(name), scheme, sig_priv.PublicKey)
	kp, err := mls.NewKeyPackageWithSecret(suite, secret, cred, sig_priv)
	if err != nil {
		return mls.SignaturePrivateKey{}, nil, fmt.Errorf("create key package: %w", err)
	}
	if err := harness.MakeKeyPackageDeterministic(kp, sig_priv); err != nil {
		return mls.SignaturePrivateKey{}, nil, fmt.Errorf("stabilize key package: %w", err)
	}
	return sig_priv, kp, nil
}

func parse_keypackage(b64 string) (mls.KeyPackage, error) {
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

func register_state_types(state *mls.State) {
	if state == nil {
		return
	}

	register_value(state.Keys)
	register_value(state.Keys.HandshakeBaseKeys)
	register_value(state.Keys.ApplicationBaseKeys)
	register_value(state.Keys.HandshakeRatchets)
	register_value(state.Keys.ApplicationRatchets)
	register_value(state.Keys.HandshakeKeys)
	register_value(state.Keys.ApplicationKeys)

	for _, ratchet := range state.Keys.HandshakeRatchets {
		register_value(ratchet)
	}
	for _, ratchet := range state.Keys.ApplicationRatchets {
		register_value(ratchet)
	}
}

func register_value(v interface{}) {
	if v == nil {
		return
	}
	gob.Register(v)
}
