{{- $gateway := .Values.server.runtimeWebGateway }}
{{- if and .Values.server.enabled $gateway.enabled $gateway.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: runtime-web-gateway
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-web-gateway") | nindent 4 }}
  {{- with $gateway.ingress.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  {{- with $gateway.ingress.className }}
  ingressClassName: {{ . | quote }}
  {{- end }}
  {{- with $gateway.ingress.tls }}
  tls:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  rules:
    {{- range $gateway.ingress.hosts }}
    - host: {{ .host | quote }}
      http:
        paths:
          - path: {{ default "/" .path | quote }}
            pathType: {{ default "Prefix" .pathType | quote }}
            backend:
              service:
                name: runtime-web-gateway
                port:
                  number: 80
    {{- end }}
{{- end }}
