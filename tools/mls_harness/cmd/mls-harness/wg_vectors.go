package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/sha512"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"hash"
	"io"
	"os"
	"path/filepath"
	"strings"

	mls "github.com/cisco/go-mls"
)

const defaultWGVectorsDir = "vectors/mlswg"
const defaultWGMaxBytes int64 = 1 << 20

// Structures mirror the trimmed MLSWG vector layout we vendor for offline use.
type cryptoBasicsFile struct {
	Description string               `json:"description"`
	Vectors     []cryptoBasicsVector `json:"vectors"`
}

type cryptoBasicsVector struct {
	Name            string             `json:"name"`
	CipherSuite     string             `json:"cipher_suite"`
	HKDFExtract     []hkdfExtractCase  `json:"hkdf_extract"`
	HKDFExpandLabel []hkdfExpandCase   `json:"hkdf_expand_label"`
	DeriveSecret    []deriveSecretCase `json:"derive_secret"`
	AEAD            []aeadCase         `json:"aead"`
}

type hkdfExtractCase struct {
	SaltHex     string `json:"salt_hex"`
	IKMHex      string `json:"ikm_hex"`
	ExpectedHex string `json:"expected_hex"`
}

type hkdfExpandCase struct {
	SecretHex   string `json:"secret_hex"`
	Label       string `json:"label"`
	ContextHex  string `json:"context_hex"`
	Length      int    `json:"length"`
	ExpectedHex string `json:"expected_hex"`
}

type deriveSecretCase struct {
	SecretHex   string `json:"secret_hex"`
	Label       string `json:"label"`
	ContextHex  string `json:"context_hex"`
	ExpectedHex string `json:"expected_hex"`
}

type aeadCase struct {
	KeyHex        string `json:"key_hex"`
	NonceHex      string `json:"nonce_hex"`
	AADHex        string `json:"aad_hex"`
	PlaintextHex  string `json:"plaintext_hex"`
	CiphertextHex string `json:"ciphertext_hex"`
}

type treeMathFile struct {
	Description string           `json:"description"`
	Vectors     []treeMathVector `json:"vectors"`
}

type treeMathVector struct {
	LeafCount    uint32              `json:"leaf_count"`
	Root         uint32              `json:"root"`
	Cases        []treeMathCase      `json:"cases"`
	FullAncestor *fullAncestor       `json:"full_ancestor"`
	InPath       []inPathExpectation `json:"in_path"`
}

type treeMathCase struct {
	Node    uint32   `json:"node"`
	Parent  uint32   `json:"parent"`
	Sibling uint32   `json:"sibling"`
	Dirpath []uint32 `json:"dirpath"`
	Copath  []uint32 `json:"copath"`
}

type fullAncestor struct {
	Left     uint32 `json:"left"`
	Right    uint32 `json:"right"`
	Expected uint32 `json:"expected"`
}

type inPathExpectation struct {
	X        uint32 `json:"x"`
	Y        uint32 `json:"y"`
	Expected bool   `json:"expected"`
}

func runWGVectors(vectorDir string, maxBytes int64) error {
	dir := vectorDir
	if dir == "" {
		dir = defaultWGVectorsDir
	}
	if maxBytes <= 0 {
		maxBytes = defaultWGMaxBytes
	}

	results := []string{}
	failed := false

	cryptoSummary, err := verifyCryptoBasics(filepath.Join(dir, "crypto-basics.json"), maxBytes)
	if err != nil {
		results = append(results, fmt.Sprintf("crypto-basics: FAIL (%v)", err))
		failed = true
	} else {
		results = append(results, fmt.Sprintf("crypto-basics: PASS (%s)", cryptoSummary))
	}

	treeSummary, err := verifyTreeMath(filepath.Join(dir, "tree-math.json"), maxBytes)
	if err != nil {
		results = append(results, fmt.Sprintf("tree-math: FAIL (%v)", err))
		failed = true
	} else {
		results = append(results, fmt.Sprintf("tree-math: PASS (%s)", treeSummary))
	}

	// Optional message-protection vectors can be added later; skip cleanly if absent.
	if _, err := os.Stat(filepath.Join(dir, "message-protection.json")); err == nil {
		results = append(results, "message-protection: SKIP (runner not yet implemented)")
	}

	for _, line := range results {
		fmt.Println(line)
	}

	if failed {
		return errors.New("MLSWG conformance vectors failed")
	}

	fmt.Println("MLSWG conformance: PASS")
	return nil
}

func verifyCryptoBasics(path string, maxBytes int64) (string, error) {
	raw, err := readVectorFile(path, maxBytes)
	if err != nil {
		return "", err
	}

	var file cryptoBasicsFile
	if err := json.Unmarshal(raw, &file); err != nil {
		return "", fmt.Errorf("parse crypto-basics: %w", err)
	}

	casesVerified := 0
	for _, vector := range file.Vectors {
		cs, ok := cipherSuiteByName(vector.CipherSuite)
		if !ok {
			return "", fmt.Errorf("unknown cipher suite %s", vector.CipherSuite)
		}
		if !cipherSuiteSupported(cs) {
			return "", fmt.Errorf("unsupported cipher suite %s", vector.CipherSuite)
		}

		for i, hk := range vector.HKDFExtract {
			salt, err := decodeHex(hk.SaltHex)
			if err != nil {
				return "", fmt.Errorf("hkdf_extract[%d] salt: %w", i, err)
			}
			ikm, err := decodeHex(hk.IKMHex)
			if err != nil {
				return "", fmt.Errorf("hkdf_extract[%d] ikm: %w", i, err)
			}
			expected, err := decodeHex(hk.ExpectedHex)
			if err != nil {
				return "", fmt.Errorf("hkdf_extract[%d] expected: %w", i, err)
			}
			derived, err := hkdfExtract(cs, salt, ikm)
			if err != nil {
				return "", fmt.Errorf("hkdf_extract[%d]: %w", i, err)
			}
			if !hmac.Equal(derived, expected) {
				return "", fmt.Errorf("hkdf_extract[%d]: mismatch", i)
			}
			casesVerified++
		}

		for i, hk := range vector.HKDFExpandLabel {
			secret, err := decodeHex(hk.SecretHex)
			if err != nil {
				return "", fmt.Errorf("hkdf_expand_label[%d] secret: %w", i, err)
			}
			context, err := decodeHex(hk.ContextHex)
			if err != nil {
				return "", fmt.Errorf("hkdf_expand_label[%d] context: %w", i, err)
			}
			expected, err := decodeHex(hk.ExpectedHex)
			if err != nil {
				return "", fmt.Errorf("hkdf_expand_label[%d] expected: %w", i, err)
			}
			derived, err := hkdfExpandLabel(cs, secret, hk.Label, context, hk.Length)
			if err != nil {
				return "", fmt.Errorf("hkdf_expand_label[%d]: %w", i, err)
			}
			if !hmac.Equal(derived, expected) {
				return "", fmt.Errorf("hkdf_expand_label[%d]: mismatch", i)
			}
			casesVerified++
		}

		for i, hk := range vector.DeriveSecret {
			secret, err := decodeHex(hk.SecretHex)
			if err != nil {
				return "", fmt.Errorf("derive_secret[%d] secret: %w", i, err)
			}
			context, err := decodeHex(hk.ContextHex)
			if err != nil {
				return "", fmt.Errorf("derive_secret[%d] context: %w", i, err)
			}
			expected, err := decodeHex(hk.ExpectedHex)
			if err != nil {
				return "", fmt.Errorf("derive_secret[%d] expected: %w", i, err)
			}
			derived, err := deriveSecret(cs, secret, hk.Label, context)
			if err != nil {
				return "", fmt.Errorf("derive_secret[%d]: %w", i, err)
			}
			if !hmac.Equal(derived, expected) {
				return "", fmt.Errorf("derive_secret[%d]: mismatch", i)
			}
			casesVerified++
		}

		for i, ac := range vector.AEAD {
			key, err := decodeHex(ac.KeyHex)
			if err != nil {
				return "", fmt.Errorf("aead[%d] key: %w", i, err)
			}
			nonce, err := decodeHex(ac.NonceHex)
			if err != nil {
				return "", fmt.Errorf("aead[%d] nonce: %w", i, err)
			}
			aad, err := decodeHex(ac.AADHex)
			if err != nil {
				return "", fmt.Errorf("aead[%d] aad: %w", i, err)
			}
			pt, err := decodeHex(ac.PlaintextHex)
			if err != nil {
				return "", fmt.Errorf("aead[%d] plaintext: %w", i, err)
			}
			expected, err := decodeHex(ac.CiphertextHex)
			if err != nil {
				return "", fmt.Errorf("aead[%d] ciphertext: %w", i, err)
			}

			aead, err := cs.NewAEAD(key)
			if err != nil {
				return "", fmt.Errorf("aead[%d]: %w", i, err)
			}
			ct := aead.Seal(nil, nonce, pt, aad)
			if !hmac.Equal(ct, expected) {
				return "", fmt.Errorf("aead[%d]: mismatch", i)
			}
			casesVerified++
		}
	}

	return fmt.Sprintf("%d cases", casesVerified), nil
}

func verifyTreeMath(path string, maxBytes int64) (string, error) {
	raw, err := readVectorFile(path, maxBytes)
	if err != nil {
		return "", err
	}

	var file treeMathFile
	if err := json.Unmarshal(raw, &file); err != nil {
		return "", fmt.Errorf("parse tree-math: %w", err)
	}

	verified := 0
	for i, vector := range file.Vectors {
		lc := mls.LeafCount(vector.LeafCount)
		if treeMathRoot(lc) != mls.NodeIndex(vector.Root) {
			return "", fmt.Errorf("vector %d: root mismatch", i)
		}

		for j, c := range vector.Cases {
			node := mls.NodeIndex(c.Node)
			if treeMathParent(node, lc) != mls.NodeIndex(c.Parent) {
				return "", fmt.Errorf("vector %d case %d: parent mismatch", i, j)
			}
			if treeMathSibling(node, lc) != mls.NodeIndex(c.Sibling) {
				return "", fmt.Errorf("vector %d case %d: sibling mismatch", i, j)
			}
			if !nodeSliceEquals(treeMathDirpath(node, lc), c.Dirpath) {
				return "", fmt.Errorf("vector %d case %d: dirpath mismatch", i, j)
			}
			if !nodeSliceEquals(treeMathCopath(node, lc), c.Copath) {
				return "", fmt.Errorf("vector %d case %d: copath mismatch", i, j)
			}
			verified++
		}

		if vector.FullAncestor != nil {
			fa := vector.FullAncestor
			if treeMathFullAncestor(mls.NodeIndex(fa.Left), mls.NodeIndex(fa.Right)) != mls.NodeIndex(fa.Expected) {
				return "", fmt.Errorf("vector %d: full_ancestor mismatch", i)
			}
			verified++
		}

		for k, ip := range vector.InPath {
			actual := treeMathInPath(mls.NodeIndex(ip.X), mls.NodeIndex(ip.Y))
			if actual != ip.Expected {
				return "", fmt.Errorf("vector %d in_path %d: expected %v got %v", i, k, ip.Expected, actual)
			}
			verified++
		}
	}

	return fmt.Sprintf("%d checks", verified), nil
}

func readVectorFile(path string, maxBytes int64) ([]byte, error) {
	stat, err := os.Stat(path)
	if err != nil {
		return nil, fmt.Errorf("stat %s: %w", path, err)
	}
	if stat.Size() > maxBytes {
		return nil, fmt.Errorf("%s exceeds %d bytes", path, maxBytes)
	}

	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open %s: %w", path, err)
	}
	defer f.Close()

	data, err := io.ReadAll(io.LimitReader(f, maxBytes))
	if err != nil {
		return nil, fmt.Errorf("read %s: %w", path, err)
	}
	return data, nil
}

func decodeHex(s string) ([]byte, error) {
	s = strings.TrimSpace(s)
	if len(s)%2 != 0 {
		return nil, fmt.Errorf("hex string must be even length: %s", s)
	}
	out, err := hex.DecodeString(s)
	if err != nil {
		return nil, fmt.Errorf("decode hex: %w", err)
	}
	return out, nil
}

func cipherSuiteByName(name string) (mls.CipherSuite, bool) {
	switch name {
	case mls.X25519_AES128GCM_SHA256_Ed25519.String():
		return mls.X25519_AES128GCM_SHA256_Ed25519, true
	case mls.P256_AES128GCM_SHA256_P256.String():
		return mls.P256_AES128GCM_SHA256_P256, true
	case mls.X25519_CHACHA20POLY1305_SHA256_Ed25519.String():
		return mls.X25519_CHACHA20POLY1305_SHA256_Ed25519, true
	case mls.P521_AES256GCM_SHA512_P521.String():
		return mls.P521_AES256GCM_SHA512_P521, true
	default:
		return 0, false
	}
}

func cipherSuiteSupported(cs mls.CipherSuite) bool {
	switch cs {
	case mls.X25519_AES128GCM_SHA256_Ed25519,
		mls.P256_AES128GCM_SHA256_P256,
		mls.P521_AES256GCM_SHA512_P521,
		mls.X25519_CHACHA20POLY1305_SHA256_Ed25519:
		return true
	default:
		return false
	}
}

func hashForSuite(cs mls.CipherSuite) (func() hash.Hash, error) {
	switch cs {
	case mls.X25519_AES128GCM_SHA256_Ed25519,
		mls.P256_AES128GCM_SHA256_P256,
		mls.X25519_CHACHA20POLY1305_SHA256_Ed25519:
		return sha256.New, nil
	case mls.P521_AES256GCM_SHA512_P521:
		return sha512.New, nil
	default:
		return nil, fmt.Errorf("unsupported digest for suite %s", cs.String())
	}
}

func hkdfExtract(cs mls.CipherSuite, salt, ikm []byte) ([]byte, error) {
	h, err := hashForSuite(cs)
	if err != nil {
		return nil, err
	}
	mac := hmac.New(h, salt)
	mac.Write(ikm)
	return mac.Sum(nil), nil
}

func hkdfExpand(cs mls.CipherSuite, secret, info []byte, size int) ([]byte, error) {
	h, err := hashForSuite(cs)
	if err != nil {
		return nil, err
	}
	last := []byte{}
	buf := []byte{}
	counter := byte(1)
	for len(buf) < size {
		mac := hmac.New(h, secret)
		mac.Write(last)
		mac.Write(info)
		mac.Write([]byte{counter})
		last = mac.Sum(nil)
		counter++
		buf = append(buf, last...)
	}
	return buf[:size], nil
}

func hkdfExpandLabel(cs mls.CipherSuite, secret []byte, label string, context []byte, length int) ([]byte, error) {
	labelData := []byte("mls10 " + label)
	labelLen := uint16(length)
	info := []byte{byte(labelLen >> 8), byte(labelLen)}
	info = append(info, byte(len(labelData)))
	info = append(info, labelData...)

	ctxLen := uint32(len(context))
	info = append(info, byte(ctxLen>>24), byte(ctxLen>>16), byte(ctxLen>>8), byte(ctxLen))
	info = append(info, context...)

	return hkdfExpand(cs, secret, info, length)
}

func deriveSecret(cs mls.CipherSuite, secret []byte, label string, context []byte) ([]byte, error) {
	h, err := hashForSuite(cs)
	if err != nil {
		return nil, err
	}
	dig := h()
	dig.Write(context)
	contextHash := dig.Sum(nil)
	size := cs.Constants().SecretSize
	return hkdfExpandLabel(cs, secret, label, contextHash, size)
}

// Tree math helpers mirror the logic in vendor/github.com/cisco/go-mls/tree-math.go.
func treeMathLog2(x uint32) uint {
	if x == 0 {
		return 0
	}
	k := uint(0)
	for (x >> k) > 0 {
		k++
	}
	return k - 1
}

func treeMathLevel(x mls.NodeIndex) uint {
	if x&0x01 == 0 {
		return 0
	}
	k := uint(0)
	for (x>>k)&0x01 == 1 {
		k++
	}
	return k
}

func treeMathNodeWidth(n mls.LeafCount) uint32 {
	return 2*uint32(n) - 1
}

func treeMathRoot(n mls.LeafCount) mls.NodeIndex {
	w := treeMathNodeWidth(n)
	return mls.NodeIndex((1 << treeMathLog2(w)) - 1)
}

func treeMathLeft(x mls.NodeIndex) mls.NodeIndex {
	if treeMathLevel(x) == 0 {
		return x
	}
	return x ^ (0x01 << (treeMathLevel(x) - 1))
}

func treeMathRight(x mls.NodeIndex, n mls.LeafCount) mls.NodeIndex {
	if treeMathLevel(x) == 0 {
		return x
	}
	w := mls.NodeIndex(treeMathNodeWidth(n))
	r := x ^ (0x03 << (treeMathLevel(x) - 1))
	for r >= w {
		r = treeMathLeft(r)
	}
	return r
}

func treeMathParentStep(x mls.NodeIndex) mls.NodeIndex {
	k := treeMathLevel(x)
	one := uint(1)
	return mls.NodeIndex((uint(x) | (one << k)) & ^(one << (k + 1)))
}

func treeMathParent(x mls.NodeIndex, n mls.LeafCount) mls.NodeIndex {
	if x == treeMathRoot(n) {
		return x
	}
	w := mls.NodeIndex(treeMathNodeWidth(n))
	p := treeMathParentStep(x)
	for p >= w {
		p = treeMathParentStep(p)
	}
	return p
}

func treeMathSibling(x mls.NodeIndex, n mls.LeafCount) mls.NodeIndex {
	p := treeMathParent(x, n)
	if x < p {
		return treeMathRight(p, n)
	} else if x > p {
		return treeMathLeft(p)
	}
	return p
}

func treeMathDirpath(x mls.NodeIndex, n mls.LeafCount) []mls.NodeIndex {
	d := []mls.NodeIndex{}
	p := treeMathParent(x, n)
	r := treeMathRoot(n)
	for p != r {
		d = append(d, p)
		p = treeMathParent(p, n)
	}
	if x != r {
		d = append(d, p)
	}
	return d
}

func treeMathCopath(x mls.NodeIndex, n mls.LeafCount) []mls.NodeIndex {
	d := treeMathDirpath(x, n)
	if len(d) == 0 {
		return []mls.NodeIndex{}
	}
	d = append([]mls.NodeIndex{x}, d[:len(d)-1]...)
	r := treeMathRoot(n)
	c := make([]mls.NodeIndex, len(d))
	for i, node := range d {
		if node == r {
			continue
		}
		c[i] = treeMathSibling(node, n)
	}
	return c
}

func treeMathInPath(x, y mls.NodeIndex) bool {
	lx, ly := treeMathLevel(x), treeMathLevel(y)
	return lx <= ly && x>>(ly+1) == y>>(ly+1)
}

func treeMathFullAncestor(l, r mls.NodeIndex) mls.NodeIndex {
	ll, lr := treeMathLevel(l)+1, treeMathLevel(r)+1
	if ll <= lr && l>>lr == r>>lr {
		return r
	}
	if lr <= ll && l>>ll == r>>ll {
		return l
	}
	k := uint(0)
	ln, rn := l, r
	for ln != rn {
		ln, rn = ln>>1, rn>>1
		k++
	}
	return mls.NodeIndex((uint(ln) << k) | ((1 << k) - 1))
}

func nodeSliceEquals(have []mls.NodeIndex, expect []uint32) bool {
	if len(have) != len(expect) {
		return false
	}
	for i, v := range have {
		if uint32(v) != expect[i] {
			return false
		}
	}
	return true
}
