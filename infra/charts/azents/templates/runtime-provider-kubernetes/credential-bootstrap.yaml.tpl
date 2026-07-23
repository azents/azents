{{- if and .Values.runtimeProviderKubernetes.enabled .Values.runtimeProviderKubernetes.credential.bootstrap.enabled }}
{{- $authSecretName := required "secrets.existingSecrets.auth is required when Runtime Provider credential bootstrap is enabled" .Values.secrets.existingSecrets.auth }}
{{- $providerSecretName := required "runtimeProviderKubernetes.credential.existingSecret is required when credential bootstrap is enabled" .Values.runtimeProviderKubernetes.credential.existingSecret }}
{{- $secretName := default $providerSecretName .Values.runtimeProviderKubernetes.credential.bootstrap.secretName }}
{{- $secretKey := required "runtimeProviderKubernetes.credential.key is required when credential bootstrap is enabled" .Values.runtimeProviderKubernetes.credential.key }}
{{- $jobDigest := dict
  "providerId" .Values.runtimeProviderKubernetes.providerId
  "secretName" $secretName
  "secretKey" $secretKey
  "serverImage" (include "azents.serverImage" .)
  | toJson
  | sha256sum
  | trunc 10
}}
apiVersion: v1
kind: Secret
metadata:
  name: {{ $secretName | quote }}
  namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-credential") | nindent 4 }}
  annotations:
    azents.io/runtime-provider-id: {{ .Values.runtimeProviderKubernetes.providerId | quote }}
type: Opaque
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ printf "%s-runtime-provider-bootstrap" (include "azents.fullname" .) | trunc 63 | trimSuffix "-" | quote }}
  namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-credential-bootstrap") | nindent 4 }}
automountServiceAccountToken: true
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ printf "%s-runtime-provider-bootstrap" (include "azents.fullname" .) | trunc 63 | trimSuffix "-" | quote }}
  namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-credential-bootstrap") | nindent 4 }}
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    resourceNames: [{{ $secretName | quote }}]
    verbs: ["get", "patch", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ printf "%s-runtime-provider-bootstrap" (include "azents.fullname" .) | trunc 63 | trimSuffix "-" | quote }}
  namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-credential-bootstrap") | nindent 4 }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: {{ printf "%s-runtime-provider-bootstrap" (include "azents.fullname" .) | trunc 63 | trimSuffix "-" | quote }}
subjects:
  - kind: ServiceAccount
    name: {{ printf "%s-runtime-provider-bootstrap" (include "azents.fullname" .) | trunc 63 | trimSuffix "-" | quote }}
    namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
---
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ printf "%s-runtime-provider-bootstrap-%s" (include "azents.fullname" .) $jobDigest | trunc 63 | trimSuffix "-" | quote }}
  namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-credential-bootstrap") | nindent 4 }}
spec:
  backoffLimit: 12
  activeDeadlineSeconds: 900
  ttlSecondsAfterFinished: 86400
  template:
    metadata:
      labels:
        {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-credential-bootstrap") | nindent 8 }}
    spec:
      restartPolicy: OnFailure
      serviceAccountName: {{ printf "%s-runtime-provider-bootstrap" (include "azents.fullname" .) | trunc 63 | trimSuffix "-" | quote }}
      {{- with .Values.global.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      containers:
        - name: enroll
          image: {{ include "azents.serverImage" . | quote }}
          imagePullPolicy: {{ .Values.server.image.pullPolicy | quote }}
          command: ["python", "src/cli/runtime_provider_bootstrap.py"]
          args:
            - "--source-key"
            - {{ printf "helm/%s/%s" .Release.Namespace .Release.Name | quote }}
            - "--source-path"
            - "/var/run/azents/runtime-provider-bootstrap/providers.yaml"
            - "--provider-id"
            - {{ .Values.runtimeProviderKubernetes.providerId | quote }}
            - "--secret-namespace"
            - {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
            - "--secret-name"
            - {{ $secretName | quote }}
            - "--secret-key"
            - {{ $secretKey | quote }}
          envFrom:
            - configMapRef:
                name: {{ include "azents.serverConfigMapName" . | quote }}
          env:
            {{- include "azents.serverAuthSecretEnv" . | nindent 12 }}
            {{- include "azents.externalServiceSecretEnv" . | nindent 12 }}
          volumeMounts:
            - name: runtime-provider-bootstrap
              mountPath: /var/run/azents/runtime-provider-bootstrap
              readOnly: true
      volumes:
        - name: runtime-provider-bootstrap
          configMap:
            name: {{ include "azents.runtimeProviderBootstrapConfigMapName" . | quote }}
{{- end }}
