{{- if and .Values.web.enabled .Values.global.rbac.create }}
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ include "azents.webServiceAccountName" . | quote }}
  namespace: {{ include "azents.webNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "web") | nindent 4 }}
rules: []
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ include "azents.webServiceAccountName" . | quote }}
  namespace: {{ include "azents.webNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "web") | nindent 4 }}
subjects:
  - kind: ServiceAccount
    name: {{ include "azents.webServiceAccountName" . | quote }}
    namespace: {{ include "azents.webNamespace" . | quote }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: {{ include "azents.webServiceAccountName" . | quote }}
{{- end }}
