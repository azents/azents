# RuntimeTerminalTicketResponse

Typed open-or-attach ticket issuance response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**status** | [**RuntimeTerminalTicketStatus**](RuntimeTerminalTicketStatus.md) |  | 
**reason_code** | [**RuntimeTerminalReasonCode**](RuntimeTerminalReasonCode.md) |  | 
**denied_scope** | [**RuntimeTerminalDeniedScope**](RuntimeTerminalDeniedScope.md) |  | 
**ticket** | **str** |  | 
**expires_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.runtime_terminal_ticket_response import RuntimeTerminalTicketResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeTerminalTicketResponse from a JSON string
runtime_terminal_ticket_response_instance = RuntimeTerminalTicketResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeTerminalTicketResponse.to_json())

# convert the object into a dict
runtime_terminal_ticket_response_dict = runtime_terminal_ticket_response_instance.to_dict()
# create an instance of RuntimeTerminalTicketResponse from a dict
runtime_terminal_ticket_response_from_dict = RuntimeTerminalTicketResponse.from_dict(runtime_terminal_ticket_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


