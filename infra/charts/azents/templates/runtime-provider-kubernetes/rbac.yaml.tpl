{{- if and .Values.runtimeProviderKubernetes.enabled .Values.global.rbac.create }}
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ printf "%s-runtime" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
  namespace: {{ include "azents.runtimeProviderKubernetesWorkloadNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["persistentvolumeclaims"]
    verbs: ["get", "list", "create", "update", "patch", "delete"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["networkpolicies"]
    verbs: ["get", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ printf "%s-runtime" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
  namespace: {{ include "azents.runtimeProviderKubernetesWorkloadNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: {{ printf "%s-runtime" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
subjects:
  - kind: ServiceAccount
    name: {{ include "azents.runtimeProviderKubernetesServiceAccountName" . | quote }}
    namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
{{- if .Values.runtimeProviderKubernetes.processContainment.runtimeClassName }}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {{ printf "%s-runtime-class" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
rules:
  - apiGroups: ["node.k8s.io"]
    resources: ["runtimeclasses"]
    resourceNames:
      - {{ .Values.runtimeProviderKubernetes.processContainment.runtimeClassName | quote }}
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: {{ printf "%s-runtime-class" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: {{ printf "%s-runtime-class" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
subjects:
  - kind: ServiceAccount
    name: {{ include "azents.runtimeProviderKubernetesServiceAccountName" . | quote }}
    namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
{{- end }}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ printf "%s-leader" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
  namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
rules:
  - apiGroups: ["coordination.k8s.io"]
    resources: ["leases"]
    verbs: ["get", "list", "create", "update", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ printf "%s-leader" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
  namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: {{ printf "%s-leader" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
subjects:
  - kind: ServiceAccount
    name: {{ include "azents.runtimeProviderKubernetesServiceAccountName" . | quote }}
    namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
{{- end }}
