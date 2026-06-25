# AcceptDeclineResponse

Invitation accept/reject response schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Invitation ID | 
**status** | [**InvitationStatus**](InvitationStatus.md) | Changed status | 

## Example

```python
from azentspublicclient.models.accept_decline_response import AcceptDeclineResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AcceptDeclineResponse from a JSON string
accept_decline_response_instance = AcceptDeclineResponse.from_json(json)
# print the JSON string representation of the object
print(AcceptDeclineResponse.to_json())

# convert the object into a dict
accept_decline_response_dict = accept_decline_response_instance.to_dict()
# create an instance of AcceptDeclineResponse from a dict
accept_decline_response_from_dict = AcceptDeclineResponse.from_dict(accept_decline_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


