/**
 * Locale translation file structure validation.
 *
 * Validates at compile time that every composed locale has the same key structure
 * as en-US. Missing keys produce type errors.
 *
 * This file is not executed at runtime and is used only during typecheck.
 */
import type en from "./en-US-messages";

type Messages = typeof en;

// Verify that each composed locale has the same key structure as en-US.
import frFR from "./fr-FR-messages";
import jaJP from "./ja-JP-messages";
import koKR from "./ko-KR-messages";

koKR satisfies Messages;
jaJP satisfies Messages;
frFR satisfies Messages;
