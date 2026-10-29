{{- $proxy := .Values.llmProxy }}
{{- if $proxy.enabled }}
{{- $name := printf "%s-llm-proxy" (include "azents.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- $repository := required "llmProxy.image.repository is required" $proxy.image.repository }}
{{- $tag := required "llmProxy.image.tag is required" $proxy.image.tag }}
{{- $image := printf "%s:%s" $repository $tag }}
{{- if $proxy.image.digest }}
{{- $image = printf "%s@%s" $image $proxy.image.digest }}
{{- end }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ $name }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "llm-proxy") | nindent 4 }}
spec:
  replicas: {{ $proxy.replicas }}
  selector:
    matchLabels:
      {{- include "azents.selectorLabels" (dict "root" . "component" "llm-proxy") | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "azents.selectorLabels" (dict "root" . "component" "llm-proxy") | nindent 8 }}
    spec:
      automountServiceAccountToken: false
      terminationGracePeriodSeconds: {{ $proxy.terminationGracePeriodSeconds }}
      securityContext:
        runAsNonRoot: true
        runAsUser: 65532
        runAsGroup: 65532
        fsGroup: 65532
      {{- with .Values.global.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      containers:
        - name: llm-proxy
          image: {{ $image | quote }}
          imagePullPolicy: {{ $proxy.image.pullPolicy }}
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
          ports:
            - name: http
              containerPort: {{ $proxy.port }}
          env:
            - name: AZ_LLM_PROXY_PORT
              value: {{ $proxy.port | quote }}
            - name: AZ_LLM_PROXY_AUTHORITY_URL
              value: {{ required "llmProxy.authority.url is required" $proxy.authority.url | quote }}
            - name: AZ_LLM_PROXY_AUTHORITY_TIMEOUT_SECONDS
              value: {{ $proxy.authority.timeoutSeconds | quote }}
            - name: AZ_LLM_PROXY_RESOLVER_KEY
              valueFrom:
                secretKeyRef:
                  name: {{ required "llmProxy.authority.resolver.existingSecret is required" $proxy.authority.resolver.existingSecret | quote }}
                  key: {{ $proxy.authority.resolver.key | quote }}
            {{- if $proxy.authority.ca.existingSecret }}
            - name: AZ_LLM_PROXY_AUTHORITY_CA_FILE
              value: /var/run/azents/authority/ca.crt
            {{- end }}
          readinessProbe:
            httpGet:
              path: /health/liveliness
              port: http
            initialDelaySeconds: 5
          livenessProbe:
            httpGet:
              path: /health/liveliness
              port: http
            initialDelaySeconds: 30
          resources:
            {{- toYaml $proxy.resources | nindent 12 }}
          {{- if $proxy.authority.ca.existingSecret }}
          volumeMounts:
            - name: authority-ca
              mountPath: /var/run/azents/authority
              readOnly: true
          {{- end }}
      {{- if $proxy.authority.ca.existingSecret }}
      volumes:
        - name: authority-ca
          secret:
            secretName: {{ $proxy.authority.ca.existingSecret | quote }}
            items:
              - key: {{ $proxy.authority.ca.key | quote }}
                path: ca.crt
      {{- end }}
---
apiVersion: v1
kind: Service
metadata:
  name: {{ $name }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "llm-proxy") | nindent 4 }}
spec:
  type: ClusterIP
  selector:
    {{- include "azents.selectorLabels" (dict "root" . "component" "llm-proxy") | nindent 4 }}
  ports:
    - name: http
      port: 80
      targetPort: http
{{- if $proxy.ingress.enabled }}
{{- if not (and $proxy.ingress.hosts $proxy.ingress.tls) }}
{{- fail "llmProxy.ingress requires explicit hosts and TLS" }}
{{- end }}
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ $name }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "llm-proxy") | nindent 4 }}
  annotations:
    {{- toYaml $proxy.ingress.annotations | nindent 4 }}
spec:
  {{- with $proxy.ingress.className }}
  ingressClassName: {{ . | quote }}
  {{- end }}
  tls:
    {{- toYaml $proxy.ingress.tls | nindent 4 }}
  rules:
    {{- range $proxy.ingress.hosts }}
    - host: {{ . | quote }}
      http:
        paths:
          {{- range list "/v1/responses" "/v1/models" }}
          - path: {{ . }}
            pathType: Exact
            backend:
              service:
                name: {{ $name }}
                port:
                  number: 80
          {{- end }}
    {{- end }}
{{- end }}
{{- end }}
