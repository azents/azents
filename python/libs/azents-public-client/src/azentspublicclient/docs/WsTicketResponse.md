# WsTicketResponse

Short-lived ticket response for WebSocket connection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**ticket** | **str** | Short-lived HMAC-signed ticket, valid for 30 seconds |

## Example

```python
from azentspublicclient.models.ws_ticket_response import WsTicketResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WsTicketResponse from a JSON string
ws_ticket_response_instance = WsTicketResponse.from_json(json)
# print the JSON string representation of the object
print(WsTicketResponse.to_json())

# convert the object into a dict
ws_ticket_response_dict = ws_ticket_response_instance.to_dict()
# create an instance of WsTicketResponse from a dict
ws_ticket_response_from_dict = WsTicketResponse.from_dict(ws_ticket_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


