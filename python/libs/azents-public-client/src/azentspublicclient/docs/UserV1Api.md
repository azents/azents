# azentspublicclient.UserV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**user_v1_get_my_system_roles**](UserV1Api.md#user_v1_get_my_system_roles) | **GET** /user/v1/me/system-roles | Get My System Roles
[**user_v1_me**](UserV1Api.md#user_v1_me) | **GET** /user/v1/me | Me


# **user_v1_get_my_system_roles**
> MySystemRolesResponse user_v1_get_my_system_roles()

Get My System Roles

Return system roles assigned to the current User.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.my_system_roles_response import MySystemRolesResponse
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
    api_instance = azentspublicclient.UserV1Api(api_client)

    try:
        # Get My System Roles
        api_response = api_instance.user_v1_get_my_system_roles()
        print("The response of UserV1Api->user_v1_get_my_system_roles:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling UserV1Api->user_v1_get_my_system_roles: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**MySystemRolesResponse**](MySystemRolesResponse.md)

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

# **user_v1_me**
> MeResponse user_v1_me()

Me

Return the currently authenticated user's information.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.me_response import MeResponse
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
    api_instance = azentspublicclient.UserV1Api(api_client)

    try:
        # Me
        api_response = api_instance.user_v1_me()
        print("The response of UserV1Api->user_v1_me:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling UserV1Api->user_v1_me: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**MeResponse**](MeResponse.md)

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

