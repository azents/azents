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
