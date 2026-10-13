# GoogleIdentity

Principal obtained only from verified signed Google identity claims.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**issuer** | **str** |  | 
**subject** | **str** |  | 
**email** | **str** |  | 

## Example

```python
from azentspublicclient.models.google_identity import GoogleIdentity

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleIdentity from a JSON string
google_identity_instance = GoogleIdentity.from_json(json)
# print the JSON string representation of the object
print(GoogleIdentity.to_json())

# convert the object into a dict
google_identity_dict = google_identity_instance.to_dict()
# create an instance of GoogleIdentity from a dict
google_identity_from_dict = GoogleIdentity.from_dict(google_identity_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


