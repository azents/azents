{{- if and .Values.server.enabled .Values.server.runtimeControl.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: runtime-control
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-control") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
spec:
  replicas: {{ .Values.server.runtimeControl.replicas }}
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "azents.name" . | quote }}
      app.kubernetes.io/instance: {{ .Release.Name | quote }}
      app.kubernetes.io/component: "runtime-control"
  template:
    metadata:
      labels:
        {{- include "azents.componentLabels" (dict "root" . "component" "runtime-control") | nindent 8 }}
        app.kubernetes.io/part-of: "azents"
    spec:
      serviceAccountName: {{ include "azents.serverServiceAccountName" . | quote }}
      {{- with .Values.global.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      containers:
        - name: runtime-control
          image: {{ include "azents.serverImage" . | quote }}
          imagePullPolicy: {{ .Values.server.image.pullPolicy | quote }}
          command: ["python", "src/cli/runtime_control_server.py"]
          ports:
            - name: grpc
              containerPort: 8030
          envFrom:
            - configMapRef:
                name: {{ include "azents.serverConfigMapName" . | quote }}
          env:
            - name: AZ_RUNTIME_CONTROL_PORT
              value: "8030"
            - name: AZ_RUNTIME_CONTROL_INSTANCE_ID
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: AZ_RUNTIME_CONTROL_RECONCILE_INTERVAL_SECONDS
              value: {{ .Values.server.runtimeControl.reconcileIntervalSeconds | quote }}
            - name: AZ_RUNTIME_CONTROL_LIFECYCLE_RETRY_DELAY_SECONDS
              value: {{ .Values.server.runtimeControl.lifecycleRetryDelaySeconds | quote }}
            - name: AZ_RUNTIME_CONTROL_START_TIMEOUT_SECONDS
              value: {{ .Values.server.runtimeControl.startTimeoutSeconds | quote }}
            - name: AZ_RUNTIME_CONTROL_AUTH_ENABLED
              value: {{ .Values.server.runtimeControl.auth.enabled | quote }}
            {{- if .Values.server.runtimeControl.auth.enabled }}
            - name: AZ_RUNTIME_CONTROL_AUTH_TOKEN
              valueFrom:
                secretKeyRef:
                  name: {{ required "server.runtimeControl.auth.existingSecret is required when Runtime Control auth is enabled" .Values.server.runtimeControl.auth.existingSecret | quote }}
                  key: {{ required "server.runtimeControl.auth.tokenKey is required when Runtime Control auth is enabled" .Values.server.runtimeControl.auth.tokenKey | quote }}
            {{- end }}
            - name: AZ_RUNTIME_RUNNER_IMAGE
              value: {{ include "azents.serverRuntimeRunnerImage" . | quote }}
            - name: AZ_RUNTIME_RUNNER_CONTROL_ENDPOINT
              value: {{ include "azents.runtimeControlEndpoint" . | quote }}
            {{- include "azents.serverAuthSecretEnv" . | nindent 12 }}
            {{- include "azents.externalServiceSecretEnv" . | nindent 12 }}
          readinessProbe:
            tcpSocket:
              port: grpc
            initialDelaySeconds: 5
            timeoutSeconds: 2
            periodSeconds: 10
          startupProbe:
            tcpSocket:
              port: grpc
            initialDelaySeconds: 5
            periodSeconds: 2
            failureThreshold: 30
          {{- with .Values.server.runtimeControl.resources }}
          resources:
            {{- toYaml . | nindent 12 }}
          {{- end }}
{{- end }}
