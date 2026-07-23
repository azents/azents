# ManagedApprovalRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**agent_id** | **str** |  | 
**workspace_id** | **str** |  | 
**agent_session_id** | **str** |  | 
**provider** | [**ExternalChannelProvider**](ExternalChannelProvider.md) |  | 
**status** | [**ExternalChannelAccessRequestStatus**](ExternalChannelAccessRequestStatus.md) |  | 
**principal_id** | **str** |  | 
**principal_label** | **str** |  | 
**principal_provider_user_id** | **str** |  | 
**resource_label** | **str** |  | 
**source_text** | **str** |  | 
**original_url** | **str** |  | 
**expires_at** | **datetime** |  | 
**decided_at** | **datetime** |  | 
**decision_summary** | **str** |  | 

## Example

```python
from azentspublicclient.models.managed_approval_request import ManagedApprovalRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedApprovalRequest from a JSON string
managed_approval_request_instance = ManagedApprovalRequest.from_json(json)
# print the JSON string representation of the object
print(ManagedApprovalRequest.to_json())

# convert the object into a dict
managed_approval_request_dict = managed_approval_request_instance.to_dict()
# create an instance of ManagedApprovalRequest from a dict
managed_approval_request_from_dict = ManagedApprovalRequest.from_dict(managed_approval_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


