# ConnectionAccessPolicyRequest

Dedicated External Channel ingress policy request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**open_access_enabled** | **bool** |  | [optional] [default to True]
**allow_bot_messages** | **bool** |  | [optional] [default to False]

## Example

```python
from azentspublicclient.models.connection_access_policy_request import ConnectionAccessPolicyRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ConnectionAccessPolicyRequest from a JSON string
connection_access_policy_request_instance = ConnectionAccessPolicyRequest.from_json(json)
# print the JSON string representation of the object
print(ConnectionAccessPolicyRequest.to_json())

# convert the object into a dict
connection_access_policy_request_dict = connection_access_policy_request_instance.to_dict()
# create an instance of ConnectionAccessPolicyRequest from a dict
connection_access_policy_request_from_dict = ConnectionAccessPolicyRequest.from_dict(connection_access_policy_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


