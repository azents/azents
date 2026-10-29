# TokenIssueRequest

Privileged issuer input, not an Agent-authenticated operation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_id** | **str** |  | 
**supply_subject** | **str** |  | 

## Example

```python
from azentsadminclient.models.token_issue_request import TokenIssueRequest

# TODO update the JSON string below
json = "{}"
# create an instance of TokenIssueRequest from a JSON string
token_issue_request_instance = TokenIssueRequest.from_json(json)
# print the JSON string representation of the object
print(TokenIssueRequest.to_json())

# convert the object into a dict
token_issue_request_dict = token_issue_request_instance.to_dict()
# create an instance of TokenIssueRequest from a dict
token_issue_request_from_dict = TokenIssueRequest.from_dict(token_issue_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


