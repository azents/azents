---
title: "Change iOS targets and build settings in the checked-in project specification; regenerate the Xcode project rather than editing generated project files."
---

# Generated Project Inputs

- Treat an application's `project.yml` and source folders as project authority.
- Regenerate through the documented command after changing targets or settings.
- Keep generated Xcode projects, DerivedData, test results, and downloaded tools
  outside Git. Build artifacts belong to CI publication, not source history.

## Bad

```text
Edit and commit Azents.xcodeproj/project.pbxproj.
```

## Good

```console
bash swift/scripts/ios.sh generate
```
