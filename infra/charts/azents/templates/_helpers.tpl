{{/*
Return the Azents chart name.
*/}}
{{- define "azents.name" -}}
{{- default .Chart.Name .Values.global.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Return the full Azents release name.
*/}}
{{- define "azents.fullname" -}}
{{- if .Values.global.fullnameOverride -}}
{{- .Values.global.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.global.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Render common chart labels.
*/}}
{{- define "azents.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
app.kubernetes.io/name: {{ include "azents.name" . | quote }}
app.kubernetes.io/instance: {{ .Release.Name | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
{{- end -}}

{{/*
Render component labels.
*/}}
{{- define "azents.componentLabels" -}}
{{ include "azents.labels" .root }}
app.kubernetes.io/component: {{ .component | quote }}
{{- end -}}

{{/*
Render stable selector labels.
*/}}
{{- define "azents.selectorLabels" -}}
app.kubernetes.io/name: {{ include "azents.name" .root | quote }}
app.kubernetes.io/instance: {{ .root.Release.Name | quote }}
app.kubernetes.io/component: {{ .component | quote }}
{{- end -}}

{{/*
Return the server namespace name.
*/}}
{{- define "azents.serverNamespace" -}}
{{- default .Release.Namespace .Values.server.namespace.name -}}
{{- end -}}

{{/*
Return the web namespace name.
*/}}
{{- define "azents.webNamespace" -}}
{{- default .Release.Namespace .Values.web.namespace.name -}}
{{- end -}}

{{/*
Return the admin web namespace name.
*/}}
{{- define "azents.adminWebNamespace" -}}
{{- default .Release.Namespace .Values.adminWeb.namespace.name -}}
{{- end -}}

{{/*
Return the runtime provider namespace name.
*/}}
{{- define "azents.runtimeProviderKubernetesNamespace" -}}
{{- include "azents.serverNamespace" . -}}
{{- end -}}

{{/*
Return the namespace where the runtime provider creates Runtime Pods and PVCs.
*/}}
{{- define "azents.runtimeProviderKubernetesWorkloadNamespace" -}}
{{- required "runtimeProviderKubernetes.workloadNamespace.name is required" .Values.runtimeProviderKubernetes.workloadNamespace.name -}}
{{- end -}}

{{/*
Return the server ConfigMap name.
*/}}
{{- define "azents.serverConfigMapName" -}}
server-env
{{- end -}}

{{/*
Return the web ConfigMap name.
*/}}
{{- define "azents.webConfigMapName" -}}
web-env
{{- end -}}

{{/*
Return the admin web ConfigMap name.
*/}}
{{- define "azents.adminWebConfigMapName" -}}
admin-web-env
{{- end -}}

{{/*
Return the web ServiceAccount name.
*/}}
{{- define "azents.webServiceAccountName" -}}
{{- if .Values.web.serviceAccount.name -}}
{{- .Values.web.serviceAccount.name -}}
{{- else if not .Values.web.serviceAccount.create -}}
{{- required "web.serviceAccount.name is required when web.serviceAccount.create is false" .Values.web.serviceAccount.name -}}
{{- else -}}
{{- printf "%s-web" (include "azents.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/*
Return the admin web ServiceAccount name.
*/}}
{{- define "azents.adminWebServiceAccountName" -}}
{{- if .Values.adminWeb.serviceAccount.name -}}
{{- .Values.adminWeb.serviceAccount.name -}}
{{- else if not .Values.adminWeb.serviceAccount.create -}}
{{- required "adminWeb.serviceAccount.name is required when adminWeb.serviceAccount.create is false" .Values.adminWeb.serviceAccount.name -}}
{{- else -}}
{{- printf "%s-admin-web" (include "azents.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/*
Return the server ServiceAccount name.
*/}}
{{- define "azents.serverServiceAccountName" -}}
{{- if .Values.server.serviceAccount.name -}}
{{- .Values.server.serviceAccount.name -}}
{{- else if not .Values.server.serviceAccount.create -}}
{{- required "server.serviceAccount.name is required when server.serviceAccount.create is false" .Values.server.serviceAccount.name -}}
{{- else -}}
{{- printf "%s-server" (include "azents.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/*
Return the Kubernetes Runtime Provider ServiceAccount name.
*/}}
{{- define "azents.runtimeProviderKubernetesServiceAccountName" -}}
{{- if .Values.runtimeProviderKubernetes.serviceAccount.name -}}
{{- .Values.runtimeProviderKubernetes.serviceAccount.name -}}
{{- else if not .Values.runtimeProviderKubernetes.serviceAccount.create -}}
{{- required "runtimeProviderKubernetes.serviceAccount.name is required when runtimeProviderKubernetes.serviceAccount.create is false" .Values.runtimeProviderKubernetes.serviceAccount.name -}}
{{- else -}}
{{- printf "%s-runtime-provider-kubernetes" (include "azents.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/*
Return the runtime-control endpoint.
*/}}
{{- define "azents.runtimeControlEndpoint" -}}
{{- if .Values.server.runtimeControl.endpoint -}}
{{- .Values.server.runtimeControl.endpoint -}}
{{- else -}}
{{- printf "runtime-control.%s.svc.cluster.local:8030" (include "azents.serverNamespace" .) -}}
{{- end -}}
{{- end -}}

{{/*
Return the apiserver internal URL.
*/}}
{{- define "azents.apiserverInternalUrl" -}}
{{- if .Values.web.api.internalUrl -}}
{{- .Values.web.api.internalUrl -}}
{{- else -}}
{{- printf "http://apiserver.%s.svc.cluster.local:8010" (include "azents.serverNamespace" .) -}}
{{- end -}}
{{- end -}}

{{/*
Return the apiserver public URL.
*/}}
{{- define "azents.apiserverPublicUrl" -}}
{{- if .Values.web.api.publicUrl -}}
{{- .Values.web.api.publicUrl -}}
{{- else -}}
{{- include "azents.apiserverInternalUrl" . -}}
{{- end -}}
{{- end -}}

{{/*
Return the Admin Web internal Public API URL.
*/}}
{{- define "azents.adminWebPublicApiUrl" -}}
{{- if .Values.adminWeb.publicApi.internalUrl -}}
{{- .Values.adminWeb.publicApi.internalUrl -}}
{{- else -}}
{{- printf "http://apiserver.%s.svc.cluster.local:8010" (include "azents.serverNamespace" .) -}}
{{- end -}}
{{- end -}}

{{/*
Return the Admin Web internal Admin API URL.
*/}}
{{- define "azents.adminserverUrl" -}}
{{- if .Values.adminWeb.adminApi.internalUrl -}}
{{- .Values.adminWeb.adminApi.internalUrl -}}
{{- else -}}
{{- printf "http://adminserver.%s.svc.cluster.local:8011" (include "azents.serverNamespace" .) -}}
{{- end -}}
{{- end -}}

{{/*
Return the externally visible Admin Web URL, falling back to its cluster Service.
*/}}
{{- define "azents.adminWebPublicUrl" -}}
{{- if .Values.adminWeb.publicUrl -}}
{{- .Values.adminWeb.publicUrl -}}
{{- else -}}
{{- printf "http://admin-web.%s.svc.cluster.local:3000" (include "azents.adminWebNamespace" .) -}}
{{- end -}}
{{- end -}}

{{/*
Return the browser-visible Main Web URL used in operator-created links.
*/}}
{{- define "azents.adminWebPublicWebUrl" -}}
{{- if .Values.adminWeb.publicWebUrl -}}
{{- .Values.adminWeb.publicWebUrl -}}
{{- else -}}
{{- printf "http://web.%s.svc.cluster.local:3000" (include "azents.webNamespace" .) -}}
{{- end -}}
{{- end -}}

{{/*
Return the database host.
*/}}
{{- define "azents.databaseHost" -}}
{{- required "database.external.host is required when database.mode is external" .Values.database.external.host -}}
{{- end -}}

{{/*
Return the Redis URL. Return an empty string when the URL is injected from a Secret.
*/}}
{{- define "azents.redisConfigUrl" -}}
{{- if .Values.redis.external.url -}}
{{- .Values.redis.external.url -}}
{{- end -}}
{{- end -}}

{{/*
Return the object storage endpoint.
*/}}
{{- define "azents.objectStorageEndpoint" -}}
{{- .Values.objectStorage.external.endpoint -}}
{{- end -}}

{{/*
Return the object storage bucket.
*/}}
{{- define "azents.objectStorageBucket" -}}
{{- .Values.objectStorage.external.bucket -}}
{{- end -}}

{{/*
Return a Docker image reference with optional digest pinning.
*/}}
{{- define "azents.imageReference" -}}
{{- $repository := required .repositoryRequiredMessage .image.repository -}}
{{- $tag := required .tagRequiredMessage .image.tag -}}
{{- if .image.digest -}}
{{- printf "%s:%s@%s" $repository $tag .image.digest -}}
{{- else -}}
{{- printf "%s:%s" $repository $tag -}}
{{- end -}}
{{- end -}}

{{/*
Return the server image.
*/}}
{{- define "azents.serverImage" -}}
{{- include "azents.imageReference" (dict "image" .Values.server.image "repositoryRequiredMessage" "server.image.repository is required" "tagRequiredMessage" "server.image.tag is required") -}}
{{- end -}}

{{/*
Return the web image.
*/}}
{{- define "azents.webImage" -}}
{{- include "azents.imageReference" (dict "image" .Values.web.image "repositoryRequiredMessage" "web.image.repository is required" "tagRequiredMessage" "web.image.tag is required") -}}
{{- end -}}

{{/*
Return the admin web image.
*/}}
{{- define "azents.adminWebImage" -}}
{{- include "azents.imageReference" (dict "image" .Values.adminWeb.image "repositoryRequiredMessage" "adminWeb.image.repository is required" "tagRequiredMessage" "adminWeb.image.tag is required") -}}
{{- end -}}

{{/*
Return the MCP egress proxy image.
*/}}
{{- define "azents.mcpEgressProxyImage" -}}
{{- include "azents.imageReference" (dict "image" .Values.server.mcpEgressProxy.image "repositoryRequiredMessage" "server.mcpEgressProxy.image.repository is required" "tagRequiredMessage" "server.mcpEgressProxy.image.tag is required") -}}
{{- end -}}

{{/*
Return the Kubernetes Runtime Provider image.
*/}}
{{- define "azents.runtimeProviderKubernetesImage" -}}
{{- include "azents.imageReference" (dict "image" .Values.runtimeProviderKubernetes.image "repositoryRequiredMessage" "runtimeProviderKubernetes.image.repository is required" "tagRequiredMessage" "runtimeProviderKubernetes.image.tag is required") -}}
{{- end -}}

{{/*
Return the Runtime Runner image for the Kubernetes Runtime Provider.
*/}}
{{- define "azents.runtimeRunnerImage" -}}
{{- include "azents.imageReference" (dict "image" .Values.runtimeProviderKubernetes.runnerImage "repositoryRequiredMessage" "runtimeProviderKubernetes.runnerImage.repository is required" "tagRequiredMessage" "runtimeProviderKubernetes.runnerImage.tag is required") -}}
{{- end -}}

{{/*
Return the Runtime Runner image for server-side Runtime Control.
*/}}
{{- define "azents.serverRuntimeRunnerImage" -}}
{{- include "azents.imageReference" (dict "image" .Values.server.runtimeControl.runnerImage "repositoryRequiredMessage" "server.runtimeControl.runnerImage.repository is required" "tagRequiredMessage" "server.runtimeControl.runnerImage.tag is required") -}}
{{- end -}}

{{/*
Render environment variables injected from the server auth Secret.
*/}}
{{- define "azents.serverAuthSecretEnv" -}}
{{- if .Values.secrets.existingSecrets.auth }}
- name: AZ_AUTH_JWT_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecrets.auth | quote }}
      key: jwt-secret-key
- name: AZ_CREDENTIAL_ENCRYPTION_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecrets.auth | quote }}
      key: credential-encryption-key
- name: AZ_SENTRY_DSN
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecrets.auth | quote }}
      key: sentry-dsn
- name: AZ_OAUTH_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecrets.auth | quote }}
      key: oauth-secret-key
- name: AZ_GITHUB_PLATFORM_APP_ID
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecrets.auth | quote }}
      key: github-platform-app-id
- name: AZ_GITHUB_PLATFORM_PRIVATE_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecrets.auth | quote }}
      key: github-platform-private-key
- name: AZ_GITHUB_PLATFORM_CLIENT_ID
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecrets.auth | quote }}
      key: github-platform-client-id
- name: AZ_GITHUB_PLATFORM_CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecrets.auth | quote }}
      key: github-platform-client-secret
{{- end }}
{{- end -}}

{{/*
Render the optional one-time system bootstrap token Secret reference.
*/}}
{{- define "azents.systemBootstrapSecretEnv" -}}
{{- if .Values.server.systemBootstrap.existingSecret }}
- name: AZ_SYSTEM_BOOTSTRAP_SETUP_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ .Values.server.systemBootstrap.existingSecret | quote }}
      key: {{ .Values.server.systemBootstrap.tokenKey | quote }}
{{- end }}
{{- end -}}

{{/*
Render environment variables injected from external service Secrets.
*/}}
{{- define "azents.externalServiceSecretEnv" -}}
{{- if .Values.secrets.existingSecrets.database }}
- name: AZ_RDB_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecrets.database | quote }}
      key: {{ .Values.database.external.passwordKey | quote }}
{{- end }}
{{- if .Values.secrets.existingSecrets.redis }}
- name: AZ_REDIS_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecrets.redis | quote }}
      key: {{ .Values.redis.external.urlKey | quote }}
{{- end }}
{{- if and (eq .Values.objectStorage.external.credentialMode "existingSecret") .Values.secrets.existingSecrets.objectStorage }}
- name: AZ_WORKSPACE_S3_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecrets.objectStorage | quote }}
      key: {{ .Values.objectStorage.external.accessKeyIdKey | quote }}
- name: AZ_WORKSPACE_S3_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecrets.objectStorage | quote }}
      key: {{ .Values.objectStorage.external.secretAccessKeyKey | quote }}
{{- end }}
{{- end -}}
