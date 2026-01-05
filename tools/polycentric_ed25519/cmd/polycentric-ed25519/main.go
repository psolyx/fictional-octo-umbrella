package main

import (
    "crypto/ed25519"
    "crypto/rand"
    "crypto/sha256"
    "encoding/base64"
    "encoding/hex"
    "encoding/json"
    "flag"
    "fmt"
    "io"
    "log"
    "os"
)

var b64 = base64.RawURLEncoding

func deriveKeypair(seedB64 string) (ed25519.PrivateKey, ed25519.PublicKey, error) {
    seed, err := b64.DecodeString(seedB64)
    if err != nil {
        return nil, nil, fmt.Errorf("invalid seed_b64: %w", err)
    }
    if l := len(seed); l != ed25519.SeedSize {
        return nil, nil, fmt.Errorf("seed must be %d bytes, got %d", ed25519.SeedSize, l)
    }
    priv := ed25519.NewKeyFromSeed(seed)
    pub := priv.Public().(ed25519.PublicKey)
    return priv, pub, nil
}

func userIDFromPub(pub ed25519.PublicKey) string {
    digest := sha256.Sum256(pub)
    return "u_" + hex.EncodeToString(digest[:])
}

func cmdGen() int {
    seed := make([]byte, ed25519.SeedSize)
    if _, err := io.ReadFull(rand.Reader, seed); err != nil {
        log.Printf("failed to read random seed: %v", err)
        return 1
    }
    priv := ed25519.NewKeyFromSeed(seed)
    pub := priv.Public().(ed25519.PublicKey)

    payload := map[string]string{
        "seed_b64":   b64.EncodeToString(seed),
        "pub_key_b64": b64.EncodeToString(pub),
        "user_id":    userIDFromPub(pub),
    }
    enc := json.NewEncoder(os.Stdout)
    enc.SetIndent("", "  ")
    if err := enc.Encode(payload); err != nil {
        log.Printf("failed to encode output: %v", err)
        return 1
    }
    return 0
}

func cmdPubKey(seedB64 string) int {
    _, pub, err := deriveKeypair(seedB64)
    if err != nil {
        log.Printf("%v", err)
        return 1
    }
    payload := map[string]string{
        "pub_key_b64": b64.EncodeToString(pub),
        "user_id":    userIDFromPub(pub),
    }
    enc := json.NewEncoder(os.Stdout)
    enc.SetIndent("", "  ")
    if err := enc.Encode(payload); err != nil {
        log.Printf("failed to encode output: %v", err)
        return 1
    }
    return 0
}

func cmdSign(seedB64 string) int {
    priv, pub, err := deriveKeypair(seedB64)
    if err != nil {
        log.Printf("%v", err)
        return 1
    }
    payload, err := io.ReadAll(os.Stdin)
    if err != nil {
        log.Printf("failed to read input: %v", err)
        return 1
    }
    sig := ed25519.Sign(priv, payload)

    output := map[string]string{
        "sig_b64":   b64.EncodeToString(sig),
        "pub_key_b64": b64.EncodeToString(pub),
        "user_id":   userIDFromPub(pub),
    }
    enc := json.NewEncoder(os.Stdout)
    enc.SetIndent("", "  ")
    if err := enc.Encode(output); err != nil {
        log.Printf("failed to encode output: %v", err)
        return 1
    }
    return 0
}

func cmdVerify(pubKeyB64, sigB64 string) int {
    pubKey, err := b64.DecodeString(pubKeyB64)
    if err != nil {
        log.Printf("invalid pub_key_b64: %v", err)
        return 1
    }
    sig, err := b64.DecodeString(sigB64)
    if err != nil {
        log.Printf("invalid sig_b64: %v", err)
        return 1
    }
    payload, err := io.ReadAll(os.Stdin)
    if err != nil {
        log.Printf("failed to read input: %v", err)
        return 1
    }
    if !ed25519.Verify(ed25519.PublicKey(pubKey), payload, sig) {
        return 1
    }
    return 0
}

func main() {
    log.SetFlags(0)
    if len(os.Args) < 2 {
        fmt.Fprintf(os.Stderr, "expected subcommand\n")
        os.Exit(1)
    }

    switch os.Args[1] {
    case "gen":
        os.Exit(cmdGen())
    case "pubkey":
        fs := flag.NewFlagSet("pubkey", flag.ExitOnError)
        seed := fs.String("seed-b64", "", "ed25519 seed (raw, base64url no padding)")
        _ = fs.Parse(os.Args[2:])
        if *seed == "" {
            fmt.Fprintf(os.Stderr, "--seed-b64 is required\n")
            os.Exit(1)
        }
        os.Exit(cmdPubKey(*seed))
    case "sign":
        fs := flag.NewFlagSet("sign", flag.ExitOnError)
        seed := fs.String("seed-b64", "", "ed25519 seed (raw, base64url no padding)")
        _ = fs.Parse(os.Args[2:])
        if *seed == "" {
            fmt.Fprintf(os.Stderr, "--seed-b64 is required\n")
            os.Exit(1)
        }
        os.Exit(cmdSign(*seed))
    case "verify":
        fs := flag.NewFlagSet("verify", flag.ExitOnError)
        pub := fs.String("pub-key-b64", "", "ed25519 public key (base64url no padding)")
        sig := fs.String("sig-b64", "", "ed25519 signature (base64url no padding)")
        _ = fs.Parse(os.Args[2:])
        if *pub == "" || *sig == "" {
            fmt.Fprintf(os.Stderr, "--pub-key-b64 and --sig-b64 are required\n")
            os.Exit(1)
        }
        os.Exit(cmdVerify(*pub, *sig))
    default:
        fmt.Fprintf(os.Stderr, "unknown subcommand: %s\n", os.Args[1])
        os.Exit(1)
    }
}
