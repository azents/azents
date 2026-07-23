{{- if and .Values.server.enabled .Values.global.rbac.create }}
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ include "azents.serverServiceAccountName" . | quote }}
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "server") | nindent 4 }}
rules: []
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ include "azents.serverServiceAccountName" . | quote }}
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "server") | nindent 4 }}
subjects:
  - kind: ServiceAccount
    name: {{ include "azents.serverServiceAccountName" . | quote }}
    namespace: {{ include "azents.serverNamespace" . | quote }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: {{ include "azents.serverServiceAccountName" . | quote }}
{{- end }}
{{- if and .Values.server.enabled .Values.server.runtimeControl.enabled .Values.global.rbac.create }}
{{- $tokenReviewScope := printf "%s/%s/%s" .Release.Namespace .Release.Name (include "azents.serverNamespace" .) | sha256sum | trunc 8 }}
{{- $tokenReviewNamePrefix := printf "%s-runtime-control-tokenreview" (include "azents.fullname" .) | trunc 54 | trimSuffix "-" }}
{{- $tokenReviewRbacName := printf "%s-%s" $tokenReviewNamePrefix $tokenReviewScope }}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {{ $tokenReviewRbacName | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-control") | nindent 4 }}
rules:
  - apiGroups: ["authentication.k8s.io"]
    resources: ["tokenreviews"]
    verbs: ["create"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: {{ $tokenReviewRbacName | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-control") | nindent 4 }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: {{ $tokenReviewRbacName | quote }}
subjects:
  - kind: ServiceAccount
    name: {{ include "azents.serverServiceAccountName" . | quote }}
    namespace: {{ include "azents.serverNamespace" . | quote }}
{{- end }}
