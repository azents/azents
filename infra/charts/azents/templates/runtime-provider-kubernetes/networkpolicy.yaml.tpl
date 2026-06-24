{{- if and .Values.runtimeProviderKubernetes.enabled .Values.runtimeProviderKubernetes.networkPolicy.enabled }}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: azents-runtime-workload-isolation
  namespace: {{ include "azents.runtimeProviderKubernetesWorkloadNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
spec:
  podSelector:
    matchLabels:
      azents/managed-by: azents-runtime-provider-kubernetes
  policyTypes:
    - Ingress
    - Egress
  ingress: []
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: {{ include "azents.serverNamespace" . | quote }}
          podSelector:
            matchLabels:
              app.kubernetes.io/component: runtime-control
              app.kubernetes.io/instance: {{ .Release.Name | quote }}
              app.kubernetes.io/name: {{ include "azents.name" . | quote }}
      ports:
        - protocol: TCP
          port: 8030
    {{- range .Values.runtimeProviderKubernetes.networkPolicy.allowedCidrs }}
    - to:
        - ipBlock:
            cidr: {{ . | quote }}
    {{- end }}
    {{- with .Values.runtimeProviderKubernetes.networkPolicy.extraEgress }}
      {{- toYaml . | nindent 4 }}
    {{- end }}
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except:
              {{- toYaml .Values.runtimeProviderKubernetes.networkPolicy.deniedCidrs | nindent 14 }}
{{- end }}
