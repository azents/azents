/**
 * Locale translation file structure validation.
 *
 * Validates at compile time that every locale file has the same key structure
 * as en-US.json. Missing keys produce type errors.
 *
 * This file is not executed at runtime and is used only during typecheck.
 */
import type en from "../../messages/en-US.json";

type Messages = typeof en;

// Verify that each locale file has the same key structure as en-US
import frFR from "../../messages/fr-FR.json";
import jaJP from "../../messages/ja-JP.json";
import koKR from "../../messages/ko-KR.json";

koKR satisfies Messages;
jaJP satisfies Messages;
frFR satisfies Messages;
