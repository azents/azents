{{- if and .Values.server.enabled .Values.server.serviceAccount.create }}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "azents.serverServiceAccountName" . | quote }}
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "server") | nindent 4 }}
{{- end }}
