{{- if and .Values.adminWeb.enabled .Values.global.rbac.create }}
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ include "azents.adminWebServiceAccountName" . | quote }}
  namespace: {{ include "azents.adminWebNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "admin-web") | nindent 4 }}
rules: []
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ include "azents.adminWebServiceAccountName" . | quote }}
  namespace: {{ include "azents.adminWebNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "admin-web") | nindent 4 }}
subjects:
  - kind: ServiceAccount
    name: {{ include "azents.adminWebServiceAccountName" . | quote }}
    namespace: {{ include "azents.adminWebNamespace" . | quote }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: {{ include "azents.adminWebServiceAccountName" . | quote }}
{{- end }}
