# TransferOwnershipRequest

Owner transfer request schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**new_owner_workspace_user_id** | **str** | New Owner WorkspaceUser ID | 

## Example

```python
from azentsadminclient.models.transfer_ownership_request import TransferOwnershipRequest

# TODO update the JSON string below
json = "{}"
# create an instance of TransferOwnershipRequest from a JSON string
transfer_ownership_request_instance = TransferOwnershipRequest.from_json(json)
# print the JSON string representation of the object
print(TransferOwnershipRequest.to_json())

# convert the object into a dict
transfer_ownership_request_dict = transfer_ownership_request_instance.to_dict()
# create an instance of TransferOwnershipRequest from a dict
transfer_ownership_request_from_dict = TransferOwnershipRequest.from_dict(transfer_ownership_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


