# azentsadminclient.InvitationV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**invitation_v1_delete_invitation**](InvitationV1Api.md#invitation_v1_delete_invitation) | **DELETE** /invitation/v1/invitations/{invitation_id} | Delete Invitation
[**invitation_v1_list_workspace_invitations**](InvitationV1Api.md#invitation_v1_list_workspace_invitations) | **GET** /invitation/v1/workspaces/{handle}/invitations | List Workspace Invitations


# **invitation_v1_delete_invitation**
> invitation_v1_delete_invitation(invitation_id)

Delete Invitation

Delete an invitation, cancelling it.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.InvitationV1Api(api_client)
    invitation_id = 'invitation_id_example' # str |

    try:
        # Delete Invitation
        api_instance.invitation_v1_delete_invitation(invitation_id)
    except Exception as e:
        print("Exception when calling InvitationV1Api->invitation_v1_delete_invitation: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **invitation_id** | **str**|  |

### Return type

void (empty response body)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **invitation_v1_list_workspace_invitations**
> InvitationListResponse invitation_v1_list_workspace_invitations(handle)

List Workspace Invitations

List workspace invitations.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.invitation_list_response import InvitationListResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.InvitationV1Api(api_client)
    handle = 'handle_example' # str |

    try:
        # List Workspace Invitations
        api_response = api_instance.invitation_v1_list_workspace_invitations(handle)
        print("The response of InvitationV1Api->invitation_v1_list_workspace_invitations:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling InvitationV1Api->invitation_v1_list_workspace_invitations: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |

### Return type

[**InvitationListResponse**](InvitationListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)
