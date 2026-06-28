# RefreshTokenResponse

Token refresh response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**access_token** | **str** | New JWT access token |
**refresh_token** | **str** | New Refresh token |
**expires_in** | **int** | Access token expiration time (seconds) |

## Example

```python
from azentspublicclient.models.refresh_token_response import RefreshTokenResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RefreshTokenResponse from a JSON string
refresh_token_response_instance = RefreshTokenResponse.from_json(json)
# print the JSON string representation of the object
print(RefreshTokenResponse.to_json())

# convert the object into a dict
refresh_token_response_dict = refresh_token_response_instance.to_dict()
# create an instance of RefreshTokenResponse from a dict
refresh_token_response_from_dict = RefreshTokenResponse.from_dict(refresh_token_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


