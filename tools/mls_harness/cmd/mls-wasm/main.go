package main

import (
	"syscall/js"

	"github.com/polycentric/fictional-octo-umbrella/tools/mls_harness/internal/harness"
)

func main() {
	js.Global().Set("verifyVectors", js.FuncOf(verifyVectors))
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
