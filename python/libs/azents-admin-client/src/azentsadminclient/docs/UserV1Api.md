# azentsadminclient.UserV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**user_v1_delete_user**](UserV1Api.md#user_v1_delete_user) | **DELETE** /user/v1/users/{user_id} | Delete User
[**user_v1_get_user**](UserV1Api.md#user_v1_get_user) | **GET** /user/v1/users/{user_id} | Get User
[**user_v1_list_users**](UserV1Api.md#user_v1_list_users) | **GET** /user/v1/users | List Users


# **user_v1_delete_user**
> user_v1_delete_user(user_id)

Delete User

Delete a User.

### Example


```python
import azentsadminclient
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.UserV1Api(api_client)
    user_id = 'user_id_example' # str | 

    try:
        # Delete User
        api_instance.user_v1_delete_user(user_id)
    except Exception as e:
        print("Exception when calling UserV1Api->user_v1_delete_user: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **user_id** | **str**|  | 

### Return type

void (empty response body)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **user_v1_get_user**
> UserResponse user_v1_get_user(user_id)

Get User

Get a User by ID.

### Example


```python
import azentsadminclient
from azentsadminclient.models.user_response import UserResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.UserV1Api(api_client)
    user_id = 'user_id_example' # str | 

    try:
        # Get User
        api_response = api_instance.user_v1_get_user(user_id)
        print("The response of UserV1Api->user_v1_get_user:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling UserV1Api->user_v1_get_user: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **user_id** | **str**|  | 

### Return type

[**UserResponse**](UserResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **user_v1_list_users**
> UserListResponse user_v1_list_users(offset=offset, limit=limit)

List Users

List all Users.

### Example


```python
import azentsadminclient
from azentsadminclient.models.user_list_response import UserListResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.UserV1Api(api_client)
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Users
        api_response = api_instance.user_v1_list_users(offset=offset, limit=limit)
        print("The response of UserV1Api->user_v1_list_users:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling UserV1Api->user_v1_list_users: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**UserListResponse**](UserListResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

