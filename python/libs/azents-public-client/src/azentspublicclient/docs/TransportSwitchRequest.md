# TransportSwitchRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**transport** | [**ExternalChannelTransport**](ExternalChannelTransport.md) |  | 

## Example

```python
from azentspublicclient.models.transport_switch_request import TransportSwitchRequest

# TODO update the JSON string below
json = "{}"
# create an instance of TransportSwitchRequest from a JSON string
transport_switch_request_instance = TransportSwitchRequest.from_json(json)
# print the JSON string representation of the object
print(TransportSwitchRequest.to_json())

# convert the object into a dict
transport_switch_request_dict = transport_switch_request_instance.to_dict()
# create an instance of TransportSwitchRequest from a dict
transport_switch_request_from_dict = TransportSwitchRequest.from_dict(transport_switch_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


