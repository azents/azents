# ManagedMultiConnectionSetup

Created redacted Multi App connection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**connection** | [**ManagedMultiConnection**](ManagedMultiConnection.md) |  | 

## Example

```python
from azentspublicclient.models.managed_multi_connection_setup import ManagedMultiConnectionSetup

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedMultiConnectionSetup from a JSON string
managed_multi_connection_setup_instance = ManagedMultiConnectionSetup.from_json(json)
# print the JSON string representation of the object
print(ManagedMultiConnectionSetup.to_json())

# convert the object into a dict
managed_multi_connection_setup_dict = managed_multi_connection_setup_instance.to_dict()
# create an instance of ManagedMultiConnectionSetup from a dict
managed_multi_connection_setup_from_dict = ManagedMultiConnectionSetup.from_dict(managed_multi_connection_setup_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


