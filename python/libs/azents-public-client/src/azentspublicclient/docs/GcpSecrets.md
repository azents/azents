# GcpSecrets

GCP service account based secrets for Google Vertex AI.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'gcp_service_account']
**service_account_json** | **str** | Service account JSON |

## Example

```python
from azentspublicclient.models.gcp_secrets import GcpSecrets

# TODO update the JSON string below
json = "{}"
# create an instance of GcpSecrets from a JSON string
gcp_secrets_instance = GcpSecrets.from_json(json)
# print the JSON string representation of the object
print(GcpSecrets.to_json())

# convert the object into a dict
gcp_secrets_dict = gcp_secrets_instance.to_dict()
# create an instance of GcpSecrets from a dict
gcp_secrets_from_dict = GcpSecrets.from_dict(gcp_secrets_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
