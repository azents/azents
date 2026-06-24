{{- $hosts := .Values.adminWeb.ingress.hosts }}
{{- if and .Values.adminWeb.enabled (or .Values.ingress.enabled .Values.adminWeb.ingress.enabled) $hosts }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: admin-web
  namespace: {{ include "azents.adminWebNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "admin-web") | nindent 4 }}
  {{- $annotations := merge (dict) .Values.ingress.annotations .Values.adminWeb.ingress.annotations }}
  {{- with $annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  {{- $className := default .Values.ingress.className .Values.adminWeb.ingress.className }}
  {{- if $className }}
  ingressClassName: {{ $className | quote }}
  {{- end }}
  {{- $tls := default .Values.ingress.tls .Values.adminWeb.ingress.tls }}
  {{- with $tls }}
  tls:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  rules:
    {{- range $hosts }}
    - host: {{ .host | quote }}
      http:
        paths:
          - path: {{ default "/" .path | quote }}
            pathType: {{ default "Prefix" .pathType | quote }}
            backend:
              service:
                name: admin-web
                port:
                  number: 3000
    {{- end }}
{{- end }}
