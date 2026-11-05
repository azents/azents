{{- if and .Values.server.enabled .Values.server.apiserver.enabled .Values.llmProxy.enabled (eq .Values.llmProxy.authority.authentication "kubernetes_service_account") }}
{{- if not .Values.global.rbac.create }}
{{- fail "Kubernetes resolver identity requires global.rbac.create" }}
{{- end }}
{{- $apiName := printf "%s-resolver-api" (include "azents.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- $scope := printf "%s/%s/%s" .Release.Namespace .Release.Name (include "azents.serverNamespace" .) | sha256sum | trunc 8 }}
{{- $rbacName := printf "%s-%s" ($apiName | trunc 54 | trimSuffix "-") $scope }}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ $apiName }}
  namespace: {{ include "azents.serverNamespace" . | quote }}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {{ $rbacName }}
rules:
  - apiGroups: ["authentication.k8s.io"]
    resources: ["tokenreviews"]
    verbs: ["create"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: {{ $rbacName }}
subjects:
  - kind: ServiceAccount
    name: {{ $apiName }}
    namespace: {{ include "azents.serverNamespace" . | quote }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: {{ $rbacName }}
{{- end }}
