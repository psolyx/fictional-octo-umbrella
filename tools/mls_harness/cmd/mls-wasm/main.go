//go:build js && wasm
// +build js,wasm

package main

import (
	"errors"
	"syscall/js"

	"github.com/polycentric/fictional-octo-umbrella/tools/mls_harness/internal/dm"
	"github.com/polycentric/fictional-octo-umbrella/tools/mls_harness/internal/harness"
)

func main() {
	js.Global().Set("verifyVectors", js.FuncOf(verifyVectors))
	js.Global().Set("dmCreateParticipant", js.FuncOf(dmCreateParticipant))
	js.Global().Set("dmInit", js.FuncOf(dmInit))
	js.Global().Set("dmJoin", js.FuncOf(dmJoin))
	js.Global().Set("dmCommitApply", js.FuncOf(dmCommitApply))
	js.Global().Set("dmEncrypt", js.FuncOf(dmEncrypt))
	js.Global().Set("dmDecrypt", js.FuncOf(dmDecrypt))
	select {}
}

func verifyVectors(_ js.Value, args []js.Value) interface{} {
	if len(args) == 0 {
		return js.ValueOf(map[string]interface{}{"ok": false, "error": "vector input is required"})
	}

	input := args[0].String()
	result, err := harness.VerifyVectorJSON([]byte(input))
	response := map[string]interface{}{
		"ok":     err == nil && result != nil && result.OK,
		"digest": "",
	}

	if result != nil {
		response["digest"] = result.Digest
	}
	if err != nil {
		response["error"] = err.Error()
	}

	return js.ValueOf(response)
}

func dmCreateParticipant(_ js.Value, args []js.Value) interface{} {
	if len(args) < 2 {
		return js.ValueOf(map[string]interface{}{"ok": false, "error": "name and seed_int are required"})
	}
	name := args[0].String()
	seedInt, err := readSeed(args[1])
	if err != nil {
		return js.ValueOf(map[string]interface{}{"ok": false, "error": err.Error()})
	}
	participantB64, keypackageB64, err := dm.KeyPackage("", name, seedInt)
	if err != nil {
		return js.ValueOf(map[string]interface{}{"ok": false, "error": err.Error()})
	}
	return js.ValueOf(map[string]interface{}{
		"ok":              true,
		"participant_b64": participantB64,
		"keypackage_b64":  keypackageB64,
	})
}

func dmInit(_ js.Value, args []js.Value) interface{} {
	if len(args) < 4 {
		return js.ValueOf(map[string]interface{}{"ok": false, "error": "participant, peer keypackage, group_id, seed_int are required"})
	}
	participantB64 := args[0].String()
	peerKeypackageB64 := args[1].String()
	groupIDB64 := args[2].String()
	seedInt, err := readSeed(args[3])
	if err != nil {
		return js.ValueOf(map[string]interface{}{"ok": false, "error": err.Error()})
	}

	participantB64, welcomeB64, commitB64, err := dm.Init(participantB64, peerKeypackageB64, groupIDB64, seedInt)
	if err != nil {
		return js.ValueOf(map[string]interface{}{"ok": false, "error": err.Error()})
	}
	return js.ValueOf(map[string]interface{}{
		"ok":              true,
		"participant_b64": participantB64,
		"welcome_b64":     welcomeB64,
		"commit_b64":      commitB64,
	})
}

func dmJoin(_ js.Value, args []js.Value) interface{} {
	if len(args) < 2 {
		return js.ValueOf(map[string]interface{}{"ok": false, "error": "participant and welcome are required"})
	}
	participantB64 := args[0].String()
	welcomeB64 := args[1].String()
	participantB64, err := dm.Join(participantB64, welcomeB64)
	if err != nil {
		return js.ValueOf(map[string]interface{}{"ok": false, "error": err.Error()})
	}
	return js.ValueOf(map[string]interface{}{
		"ok":              true,
		"participant_b64": participantB64,
	})
}

func dmCommitApply(_ js.Value, args []js.Value) interface{} {
	if len(args) < 2 {
		return js.ValueOf(map[string]interface{}{"ok": false, "error": "participant and commit are required"})
	}
	participantB64 := args[0].String()
	commitB64 := args[1].String()
	participantB64, noop, err := dm.CommitApply(participantB64, commitB64)
	if err != nil {
		return js.ValueOf(map[string]interface{}{"ok": false, "error": err.Error()})
	}
	return js.ValueOf(map[string]interface{}{
		"ok":              true,
		"participant_b64": participantB64,
		"noop":            noop,
	})
}

func dmEncrypt(_ js.Value, args []js.Value) interface{} {
	if len(args) < 2 {
		return js.ValueOf(map[string]interface{}{"ok": false, "error": "participant and plaintext are required"})
	}
	participantB64 := args[0].String()
	plaintext := args[1].String()
	participantB64, ciphertextB64, err := dm.Encrypt(participantB64, plaintext)
	if err != nil {
		return js.ValueOf(map[string]interface{}{"ok": false, "error": err.Error()})
	}
	return js.ValueOf(map[string]interface{}{
		"ok":              true,
		"participant_b64": participantB64,
		"ciphertext_b64":  ciphertextB64,
	})
}

func dmDecrypt(_ js.Value, args []js.Value) interface{} {
	if len(args) < 2 {
		return js.ValueOf(map[string]interface{}{"ok": false, "error": "participant and ciphertext are required"})
	}
	participantB64 := args[0].String()
	ciphertextB64 := args[1].String()
	participantB64, plaintext, err := dm.Decrypt(participantB64, ciphertextB64)
	if err != nil {
		return js.ValueOf(map[string]interface{}{"ok": false, "error": err.Error()})
	}
	return js.ValueOf(map[string]interface{}{
		"ok":              true,
		"participant_b64": participantB64,
		"plaintext":       plaintext,
	})
}

func readSeed(value js.Value) (int64, error) {
	if value.Type() != js.TypeNumber {
		return 0, errors.New("seed_int must be a number")
	}
	return int64(value.Int()), nil
}
