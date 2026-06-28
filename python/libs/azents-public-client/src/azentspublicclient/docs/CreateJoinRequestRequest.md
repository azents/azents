# CreateJoinRequestRequest

Join request creation request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**message** | **str** |  | [optional]

## Example

```python
from azentspublicclient.models.create_join_request_request import CreateJoinRequestRequest

# TODO update the JSON string below
json = "{}"
# create an instance of CreateJoinRequestRequest from a JSON string
create_join_request_request_instance = CreateJoinRequestRequest.from_json(json)
# print the JSON string representation of the object
print(CreateJoinRequestRequest.to_json())

# convert the object into a dict
create_join_request_request_dict = create_join_request_request_instance.to_dict()
# create an instance of CreateJoinRequestRequest from a dict
create_join_request_request_from_dict = CreateJoinRequestRequest.from_dict(create_join_request_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


