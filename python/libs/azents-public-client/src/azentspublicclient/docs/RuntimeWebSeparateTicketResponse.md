# RuntimeWebSeparateTicketResponse

One-use POST-body ticket for the exact endpoint.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**ticket_secret** | **str** |  | 
**endpoint_id** | **str** |  | 
**expires_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_separate_ticket_response import RuntimeWebSeparateTicketResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebSeparateTicketResponse from a JSON string
runtime_web_separate_ticket_response_instance = RuntimeWebSeparateTicketResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebSeparateTicketResponse.to_json())

# convert the object into a dict
runtime_web_separate_ticket_response_dict = runtime_web_separate_ticket_response_instance.to_dict()
# create an instance of RuntimeWebSeparateTicketResponse from a dict
runtime_web_separate_ticket_response_from_dict = RuntimeWebSeparateTicketResponse.from_dict(runtime_web_separate_ticket_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


