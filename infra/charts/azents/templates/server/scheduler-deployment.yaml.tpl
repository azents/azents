{{- if and .Values.server.enabled .Values.server.scheduler.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: scheduler
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "scheduler") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "azents.name" . | quote }}
      app.kubernetes.io/instance: {{ .Release.Name | quote }}
      app.kubernetes.io/component: "scheduler"
  template:
    metadata:
      labels:
        {{- include "azents.componentLabels" (dict "root" . "component" "scheduler") | nindent 8 }}
        app.kubernetes.io/part-of: "azents"
        {{- with .Values.global.podLabels }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      {{- with .Values.global.podAnnotations }}
      annotations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
    spec:
      terminationGracePeriodSeconds: 60
      serviceAccountName: {{ include "azents.serverServiceAccountName" . | quote }}
      {{- with .Values.global.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      containers:
        - name: scheduler
          image: {{ include "azents.serverImage" . | quote }}
          imagePullPolicy: {{ .Values.server.image.pullPolicy | quote }}
          command: ["./bin/scheduler.sh"]
          envFrom:
            - configMapRef:
                name: {{ include "azents.serverConfigMapName" . | quote }}
          env:
            {{- include "azents.serverAuthSecretEnv" . | nindent 12 }}
            {{- include "azents.externalServiceSecretEnv" . | nindent 12 }}
          {{- with .Values.server.scheduler.resources }}
          resources:
            {{- toYaml . | nindent 12 }}
          {{- end }}
{{- end }}
