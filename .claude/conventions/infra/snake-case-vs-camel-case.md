---
title: "Terraform module variables use `snake_case`; ECS Container Definition fields and other inline AWS API JSON use `camelCase` (`portMappings`, `logConfiguration`, `readonlyRootFilesystem`) — match the AWS API spec exactly inside the Container Definition."
---

# Snake Case for Terraform, Camel Case Inside AWS API JSON

The split mirrors what AWS expects. Terraform-native HCL is snake_case; embedded AWS API payloads (Container Definition, IAM Policy) are camelCase per the AWS spec, and AWS rejects snake_case fields there.

- Terraform variables, locals, outputs, resource arguments → `snake_case`
- ECS Container Definition keys → `camelCase` (matches `RegisterTaskDefinition` API)
- IAM policy JSON → `PascalCase` (`Effect`, `Action`, `Resource`) per AWS

## Bad

```hcl
container_definitions = jsonencode([{
  port_mappings = [{ container_port = 8080 }]   # snake_case in AWS API → rejected
  log_configuration = { ... }
}])
```

## Good

```hcl
container_definitions = jsonencode([{
  portMappings = [{ containerPort = 8080 }]
  logConfiguration = { ... }
  readonlyRootFilesystem = true
}])
```
