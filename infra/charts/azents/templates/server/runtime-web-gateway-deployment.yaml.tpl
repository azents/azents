{{- $gateway := .Values.server.runtimeWebGateway }}
{{- $control := .Values.server.runtimeControl }}
{{- if and .Values.server.enabled $gateway.enabled }}
{{- if not $control.enabled }}
{{- fail "server.runtimeControl.enabled is required when Runtime Web Gateway is enabled" }}
{{- end }}
{{- if not $control.webTransport.enabled }}
{{- fail "server.runtimeControl.webTransport.enabled is required when Runtime Web Gateway is enabled" }}
{{- end }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: runtime-web-gateway
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-web-gateway") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
spec:
  {{- if not $gateway.autoscaling.enabled }}
  replicas: {{ $gateway.replicas }}
  {{- end }}
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "azents.name" . | quote }}
      app.kubernetes.io/instance: {{ .Release.Name | quote }}
      app.kubernetes.io/component: "runtime-web-gateway"
  template:
    metadata:
      labels:
        {{- include "azents.componentLabels" (dict "root" . "component" "runtime-web-gateway") | nindent 8 }}
        app.kubernetes.io/part-of: "azents"
    spec:
      serviceAccountName: {{ include "azents.serverServiceAccountName" . | quote }}
      {{- with .Values.global.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      containers:
        - name: runtime-web-gateway
          image: {{ include "azents.serverImage" . | quote }}
          imagePullPolicy: {{ .Values.server.image.pullPolicy | quote }}
          command: ["./bin/runtime-web-gateway.sh"]
          ports:
            - name: http
              containerPort: {{ $gateway.port }}
          envFrom:
            - configMapRef:
                name: {{ include "azents.serverConfigMapName" . | quote }}
          env:
            - name: AZ_RUNTIME_WEB_GATEWAY_ENABLED
              value: "true"
            - name: AZ_RUNTIME_WEB_GATEWAY_PORT
              value: {{ printf "%d" (int64 $gateway.port) | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_AUTH_MODE
              value: {{ $gateway.authMode | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_AUTH_CONFIGURATION_VERSION
              value: {{ printf "%d" (int64 $gateway.authConfigurationVersion) | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_MAIN_WEB_ORIGIN
              value: {{ required "server.runtimeWebGateway.mainWebOrigin is required" $gateway.mainWebOrigin | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_BROKER_ORIGIN
              value: {{ required "server.runtimeWebGateway.brokerOrigin is required" $gateway.brokerOrigin | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_SERVICE_SUFFIX
              value: {{ required "server.runtimeWebGateway.serviceSuffix is required" $gateway.serviceSuffix | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_COOKIE_DOMAIN
              value: {{ required "server.runtimeWebGateway.cookieDomain is required" $gateway.cookieDomain | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_IDENTITY_COOKIE_NAME
              value: {{ $gateway.identityCookieName | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_IDENTITY_LIFETIME_SECONDS
              value: {{ printf "%d" (int64 $gateway.identityLifetimeSeconds) | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_ACTIVE_DURATION_SECONDS
              value: {{ printf "%d" (int64 $gateway.activeDurationSeconds) | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_CHROMIUM_MIN_VERSION
              value: {{ printf "%d" (int64 $gateway.chromium.minVersion) | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_CHROMIUM_MAX_VERSION
              value: {{ printf "%d" (int64 $gateway.chromium.maxVersion) | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_REQUEST_HEADER_BYTES
              value: {{ printf "%d" (int64 $gateway.request.headerBytes) | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_REQUEST_BODY_BYTES
              value: {{ printf "%d" (int64 $gateway.request.bodyBytes) | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_FRAME_BYTES
              value: {{ printf "%d" (int64 $gateway.request.frameBytes) | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_HTTP_ENDPOINT_CONNECTIONS
              value: {{ printf "%d" (int64 $gateway.connectionLimits.http.endpoint) | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_HTTP_USER_CONNECTIONS
              value: {{ printf "%d" (int64 $gateway.connectionLimits.http.user) | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_HTTP_AGENT_CONNECTIONS
              value: {{ printf "%d" (int64 $gateway.connectionLimits.http.agent) | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_WEBSOCKET_ENDPOINT_CONNECTIONS
              value: {{ printf "%d" (int64 $gateway.connectionLimits.websocket.endpoint) | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_WEBSOCKET_USER_CONNECTIONS
              value: {{ printf "%d" (int64 $gateway.connectionLimits.websocket.user) | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_WEBSOCKET_AGENT_CONNECTIONS
              value: {{ printf "%d" (int64 $gateway.connectionLimits.websocket.agent) | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_SECURITY_PERMISSIONS_POLICY
              value: {{ $gateway.permissionsPolicy | quote }}
            - name: AZ_RUNTIME_WEB_GATEWAY_CONTROL_ENDPOINT
              value: "runtime-control:{{ $control.webTransport.trustedPort }}"
            - name: AZ_RUNTIME_WEB_GATEWAY_CONTROL_ALLOW_INSECURE
              value: "false"
            - name: AZ_RUNTIME_WEB_GATEWAY_CONTROL_TLS_CA_FILE
              value: "/var/run/secrets/azents/runtime-web-control-tls/ca.crt"
            - name: AZ_RUNTIME_WEB_GATEWAY_CONTROL_TLS_CERTIFICATE_FILE
              value: "/var/run/secrets/azents/runtime-web-control-tls/tls.crt"
            - name: AZ_RUNTIME_WEB_GATEWAY_CONTROL_TLS_PRIVATE_KEY_FILE
              value: "/var/run/secrets/azents/runtime-web-control-tls/tls.key"
            {{- include "azents.externalServiceSecretEnv" . | nindent 12 }}
          volumeMounts:
            - name: runtime-web-control-tls
              mountPath: /var/run/secrets/azents/runtime-web-control-tls
              readOnly: true
          readinessProbe:
            httpGet:
              path: /__azents/ready
              port: http
            initialDelaySeconds: 5
            periodSeconds: 10
            timeoutSeconds: 2
          startupProbe:
            httpGet:
              path: /__azents/ready
              port: http
            initialDelaySeconds: 2
            periodSeconds: 2
            failureThreshold: 30
          {{- with $gateway.resources }}
          resources:
            {{- toYaml . | nindent 12 }}
          {{- end }}
      volumes:
        - name: runtime-web-control-tls
          secret:
            secretName: {{ required "server.runtimeWebGateway.controlTls.existingSecret is required" $gateway.controlTls.existingSecret | quote }}
            items:
              - key: {{ $gateway.controlTls.certificateKey | quote }}
                path: tls.crt
              - key: {{ $gateway.controlTls.privateKeyKey | quote }}
                path: tls.key
              - key: {{ $gateway.controlTls.caKey | quote }}
                path: ca.crt
{{- end }}
