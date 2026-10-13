# GoogleExchangeRequest

Transient code and encrypted state, not caller-selected target identity.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**code** | **str** |  | 
**state** | **str** |  | 

## Example

```python
from azentspublicclient.models.google_exchange_request import GoogleExchangeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleExchangeRequest from a JSON string
google_exchange_request_instance = GoogleExchangeRequest.from_json(json)
# print the JSON string representation of the object
print(GoogleExchangeRequest.to_json())

# convert the object into a dict
google_exchange_request_dict = google_exchange_request_instance.to_dict()
# create an instance of GoogleExchangeRequest from a dict
google_exchange_request_from_dict = GoogleExchangeRequest.from_dict(google_exchange_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


