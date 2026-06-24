# azentspublicclient.InvitationV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**invitation_v1_accept_invitation**](InvitationV1Api.md#invitation_v1_accept_invitation) | **POST** /invitation/v1/invitations/{invitation_id}/accept | Accept Invitation
[**invitation_v1_cancel_invitation**](InvitationV1Api.md#invitation_v1_cancel_invitation) | **DELETE** /invitation/v1/workspaces/{handle}/invitations/{invitation_id} | Cancel Invitation
[**invitation_v1_create_invitation**](InvitationV1Api.md#invitation_v1_create_invitation) | **POST** /invitation/v1/workspaces/{handle}/invitations | Create Invitation
[**invitation_v1_decline_invitation**](InvitationV1Api.md#invitation_v1_decline_invitation) | **POST** /invitation/v1/invitations/{invitation_id}/decline | Decline Invitation
[**invitation_v1_get_my_invitation**](InvitationV1Api.md#invitation_v1_get_my_invitation) | **GET** /invitation/v1/workspaces/{handle}/invitations/me | Get My Invitation
[**invitation_v1_list_received_invitations**](InvitationV1Api.md#invitation_v1_list_received_invitations) | **GET** /invitation/v1/invitations/received | List Received Invitations
[**invitation_v1_list_workspace_invitations**](InvitationV1Api.md#invitation_v1_list_workspace_invitations) | **GET** /invitation/v1/workspaces/{handle}/invitations | List Workspace Invitations


# **invitation_v1_accept_invitation**
> AcceptDeclineResponse invitation_v1_accept_invitation(invitation_id)

Accept Invitation

Accept an invitation.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.accept_decline_response import AcceptDeclineResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.InvitationV1Api(api_client)
    invitation_id = 'invitation_id_example' # str |

    try:
        # Accept Invitation
        api_response = api_instance.invitation_v1_accept_invitation(invitation_id)
        print("The response of InvitationV1Api->invitation_v1_accept_invitation:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling InvitationV1Api->invitation_v1_accept_invitation: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **invitation_id** | **str**|  |

### Return type

[**AcceptDeclineResponse**](AcceptDeclineResponse.md)

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

# **invitation_v1_cancel_invitation**
> invitation_v1_cancel_invitation(invitation_id, handle)

Cancel Invitation

Cancel an invitation.

Requires manager-or-higher permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.InvitationV1Api(api_client)
    invitation_id = 'invitation_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Cancel Invitation
        api_instance.invitation_v1_cancel_invitation(invitation_id, handle)
    except Exception as e:
        print("Exception when calling InvitationV1Api->invitation_v1_cancel_invitation: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **invitation_id** | **str**|  |
 **handle** | **str**|  |

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

# **invitation_v1_create_invitation**
> InvitationResponse invitation_v1_create_invitation(handle, create_invitation_request)

Create Invitation

Invite a user to a workspace.

Requires manager-or-higher permission. Handles new invitations, re-inviting
rejected invitations, and resending emails for pending invitations.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.create_invitation_request import CreateInvitationRequest
from azentspublicclient.models.invitation_response import InvitationResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.InvitationV1Api(api_client)
    handle = 'handle_example' # str |
    create_invitation_request = azentspublicclient.CreateInvitationRequest() # CreateInvitationRequest |

    try:
        # Create Invitation
        api_response = api_instance.invitation_v1_create_invitation(handle, create_invitation_request)
        print("The response of InvitationV1Api->invitation_v1_create_invitation:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling InvitationV1Api->invitation_v1_create_invitation: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |
 **create_invitation_request** | [**CreateInvitationRequest**](CreateInvitationRequest.md)|  |

### Return type

[**InvitationResponse**](InvitationResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **invitation_v1_decline_invitation**
> AcceptDeclineResponse invitation_v1_decline_invitation(invitation_id)

Decline Invitation

Reject an invitation.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.accept_decline_response import AcceptDeclineResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.InvitationV1Api(api_client)
    invitation_id = 'invitation_id_example' # str |

    try:
        # Decline Invitation
        api_response = api_instance.invitation_v1_decline_invitation(invitation_id)
        print("The response of InvitationV1Api->invitation_v1_decline_invitation:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling InvitationV1Api->invitation_v1_decline_invitation: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **invitation_id** | **str**|  |

### Return type

[**AcceptDeclineResponse**](AcceptDeclineResponse.md)

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

# **invitation_v1_get_my_invitation**
> InvitationResponse invitation_v1_get_my_invitation(handle)

Get My Invitation

Get my invitation for the workspace.

Non-members can also call this.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.invitation_response import InvitationResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.InvitationV1Api(api_client)
    handle = 'handle_example' # str |

    try:
        # Get My Invitation
        api_response = api_instance.invitation_v1_get_my_invitation(handle)
        print("The response of InvitationV1Api->invitation_v1_get_my_invitation:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling InvitationV1Api->invitation_v1_get_my_invitation: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |

### Return type

[**InvitationResponse**](InvitationResponse.md)

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

# **invitation_v1_list_received_invitations**
> ReceivedInvitationListResponse invitation_v1_list_received_invitations()

List Received Invitations

List pending invitations received by the current user.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.received_invitation_list_response import ReceivedInvitationListResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.InvitationV1Api(api_client)

    try:
        # List Received Invitations
        api_response = api_instance.invitation_v1_list_received_invitations()
        print("The response of InvitationV1Api->invitation_v1_list_received_invitations:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling InvitationV1Api->invitation_v1_list_received_invitations: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**ReceivedInvitationListResponse**](ReceivedInvitationListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **invitation_v1_list_workspace_invitations**
> InvitationListResponse invitation_v1_list_workspace_invitations(handle)

List Workspace Invitations

List invitations for a workspace.

Requires manager-or-higher permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.invitation_list_response import InvitationListResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.InvitationV1Api(api_client)
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
