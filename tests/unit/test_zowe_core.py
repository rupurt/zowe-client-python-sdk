"""Unit tests for the Zowe Python SDK Core package."""

# Including necessary paths
import base64
import json
import os
import shutil
import keyring
import sys
import unittest
from unittest import mock
from unittest.mock import patch , call
from jsonschema import validate, ValidationError
from zowe.core_for_zowe_sdk.validators import validate_config_json
import commentjson
from pyfakefs.fake_filesystem_unittest import TestCase
from zowe.core_for_zowe_sdk import (
    ApiConnection,
    ConfigFile,
    ProfileManager,
    CredentialManager,
    RequestHandler,
    SdkApi,
    ZosmfProfile,
    exceptions,
    session_constants,
    custom_warnings,
    constants,
)

FIXTURES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
CWD = os.getcwd()
CRED_DICT: dict = {}
SECURE_CONFIG_PROPS: bytes


def keyring_get_password(serviceName: str, username: str):
    global SECURE_CONFIG_PROPS
    return SECURE_CONFIG_PROPS


def keyring_get_password_exception():
    raise Exception


class TestApiConnectionClass(unittest.TestCase):
    """ApiConnection class unit tests."""

    def setUp(self):
        """Setup ApiConnection fixtures."""
        self.url = "https://mock-url.com"
        self.user = "Username"
        self.password = "Password"

    def test_object_should_be_instance_of_class(self):
        """Created object should be instance of ApiConnection class."""
        api_connection = ApiConnection(self.url, self.user, self.password)
        self.assertIsInstance(api_connection, ApiConnection)

    def test_object_should_raise_custom_error_without_url(self):
        """Instantiation of ApiConnection object should raise MissingConnectionArgs if host_url is blank."""
        with self.assertRaises(exceptions.MissingConnectionArgs):
            ApiConnection(host_url="", user=self.user, password=self.password)

    def test_object_should_raise_custom_error_without_user(self):
        """Instantiation of ApiConnection object should raise MissingConnectionArgs if user is blank."""
        with self.assertRaises(exceptions.MissingConnectionArgs):
            ApiConnection(host_url=self.url, user="", password=self.password)

    def test_object_should_raise_custom_error_without_password(self):
        """Instantiation of ApiConnection object should raise MissingConnectionArgs if password is blank."""
        with self.assertRaises(exceptions.MissingConnectionArgs):
            ApiConnection(host_url=self.url, user=self.user, password="")


class TestSdkApiClass(TestCase):
    """SdkApi class unit tests."""

    def setUp(self):
        """Setup fixtures for SdkApi class."""
        common_props = {
            "host": "mock-url.com",
            "port": 443,
            "protocol": "https",
            "rejectUnauthorized": True
        }
        self.basic_props = {**common_props, "user": "Username", "password": "Password"}
        self.bearer_props = {**common_props, "tokenValue": "BearerToken"}
        self.token_props = {
            **common_props,
            "tokenType": "MyToken",
            "tokenValue": "TokenValue",
        }
        self.default_url = "https://default-api.com/"

    def test_object_should_be_instance_of_class(self):
        """Created object should be instance of SdkApi class."""
        sdk_api = SdkApi(self.basic_props, self.default_url)
        self.assertIsInstance(sdk_api, SdkApi)

    def test_should_handle_basic_auth(self):
        """Created object should handle basic authentication."""
        sdk_api = SdkApi(self.basic_props, self.default_url)
        self.assertEqual(sdk_api.session.type, session_constants.AUTH_TYPE_BASIC)
        self.assertEqual(
            sdk_api.request_arguments["auth"],
            (self.basic_props["user"], self.basic_props["password"]),
        )

    def test_should_handle_bearer_auth(self):
        """Created object should handle bearer authentication."""
        sdk_api = SdkApi(self.bearer_props, self.default_url)
        self.assertEqual(sdk_api.session.type, session_constants.AUTH_TYPE_BEARER)
        self.assertEqual(
            sdk_api.default_headers["Authorization"],
            "Bearer " + self.bearer_props["tokenValue"],
        )

    def test_should_handle_token_auth(self):
        """Created object should handle token authentication."""
        sdk_api = SdkApi(self.token_props, self.default_url)
        self.assertEqual(sdk_api.session.type, session_constants.AUTH_TYPE_TOKEN)
        self.assertEqual(
            sdk_api.default_headers["Cookie"],
            self.token_props["tokenType"] + "=" + self.token_props["tokenValue"],
        )


class TestRequestHandlerClass(unittest.TestCase):
    """RequestHandler class unit tests."""

    def setUp(self):
        """Setup fixtures for RequestHandler class."""
        self.session_arguments = {"verify": False}

    def test_object_should_be_instance_of_class(self):
        """Created object should be instance of RequestHandler class."""
        request_handler = RequestHandler(self.session_arguments)
        self.assertIsInstance(request_handler, RequestHandler)

    @mock.patch("requests.Session.send")
    def test_perform_streamed_request(self, mock_send_request):
        """Performing a streamed request should call 'send_request' method"""
        mock_send_request.return_value = mock.Mock(status_code=200)
        request_handler = RequestHandler(self.session_arguments)
        request_handler.perform_streamed_request("GET", {"url": "https://www.zowe.org"})
        mock_send_request.assert_called_once()
        self.assertTrue(mock_send_request.call_args[1]["stream"])


class TestZosmfProfileClass(unittest.TestCase):
    """ZosmfProfile class unit tests."""

    def setUp(self):
        """Setup fixtures for ZosmfProfile class."""
        self.profile_name = "MOCK"

    def test_object_should_be_instance_of_class(self):
        """Created object should be instance of ZosmfProfile class."""
        zosmf_profile = ZosmfProfile(self.profile_name)
        self.assertIsInstance(zosmf_profile, ZosmfProfile)

class TestZosmfProfileManager(TestCase):
    """ProfileManager class unit tests."""

    def setUp(self):
        """Setup fixtures for ZosmfProfile class."""
        # setup pyfakefs
        self.setUpPyfakefs()
        self.original_file_path = os.path.join(FIXTURES_PATH, "zowe.config.json")
        self.original_user_file_path = os.path.join(
            FIXTURES_PATH, "zowe.config.user.json"
        )
        self.original_nested_file_path = os.path.join(
            FIXTURES_PATH, "nested.zowe.config.json"
        )
        self.original_schema_file_path = os.path.join(
            FIXTURES_PATH, "zowe.schema.json"
        )
        self.fs.add_real_file(self.original_file_path)
        self.fs.add_real_file(self.original_user_file_path)
        self.fs.add_real_file(self.original_nested_file_path)
        self.fs.add_real_file(self.original_schema_file_path)

        self.custom_dir = os.path.dirname(FIXTURES_PATH)
        self.custom_appname = "zowe_abcd"
        self.custom_filename = f"{self.custom_appname}.config.json"

        # setup keyring
        home = os.path.expanduser("~")
        self.global_config_path = os.path.join(home, ".zowe", "zowe.config.json")

    def setUpCreds(self, file_path, secure_props):
        global CRED_DICT
        # we are not storing global config properties since they are not
        # accessible within pyfakefs
        # todo : add a test that check loading from gloabl config path
        CRED_DICT = {
            file_path: secure_props,
        }

        global SECURE_CONFIG_PROPS
        SECURE_CONFIG_PROPS = base64.b64encode((json.dumps(CRED_DICT)).encode("utf-8"))
        if sys.platform == "win32":
            SECURE_CONFIG_PROPS = SECURE_CONFIG_PROPS.decode("utf-16")

    @patch("keyring.get_password", side_effect=keyring_get_password)
    def test_autodiscovery_and_base_profile_loading(self, get_pass_func):
        """
        Test loading of correct file by autodiscovering from current working directory
        also load by profile_type correctly populating fields from base profile
        and secure credentials
        """

        # Setup - copy profile to fake filesystem created by pyfakefs
        cwd_up_dir_path = os.path.dirname(CWD)
        cwd_up_file_path = os.path.join(cwd_up_dir_path, "zowe.config.json")
        os.chdir(CWD)
        shutil.copy(self.original_file_path, cwd_up_file_path)

        self.setUpCreds(cwd_up_file_path, {
            "profiles.base.properties.user": "user",
            "profiles.base.properties.password": "password",
        })

        # Test
        prof_manager = ProfileManager()
        props: dict = prof_manager.load(profile_type="base")
        self.assertEqual(prof_manager.config_filepath, cwd_up_file_path)

        expected_props = {
            "host": "zowe.test.cloud",
            "rejectUnauthorized": False,
            "user": "user",
            "password": "password",
        }
        self.assertEqual(props, expected_props)

    @patch("keyring.get_password", side_effect=keyring_get_password)
    def test_custom_file_and_custom_profile_loading(self, get_pass_func):
        """
        Test loading of correct file given a filename and directory,
        also load by profile_name correctly populating fields from custom
        profile and secure credentials
        """
        # Setup - copy profile to fake filesystem created by pyfakefs
        custom_file_path = os.path.join(self.custom_dir, self.custom_filename)
        shutil.copy(self.original_file_path, custom_file_path)

        self.setUpCreds(custom_file_path, {
            "profiles.zosmf.properties.user": "user",
            "profiles.zosmf.properties.password": "password",
        })

        # Test
        prof_manager = ProfileManager(appname=self.custom_appname)
        prof_manager.config_dir = self.custom_dir
        props: dict = prof_manager.load(profile_name="zosmf")
        self.assertEqual(prof_manager.config_filepath, custom_file_path)

        expected_props = {
            "host": "zowe.test.cloud",
            "rejectUnauthorized": False,
            "user": "user",
            "password": "password",
            "port": 10443,
        }
        self.assertEqual(props, expected_props)

    @patch("keyring.get_password", side_effect=keyring_get_password)
    def test_custom_file_and_custom_profile_loading_with_nested_profile(self, get_pass_func):
        """
        Test loading of correct file given a filename and directory,
        also load by profile_name correctly populating fields from custom
        profile and secure credentials
        """
        # Setup - copy profile to fake filesystem created by pyfakefs
        custom_file_path = os.path.join(self.custom_dir, self.custom_filename)
        shutil.copy(self.original_nested_file_path, custom_file_path)

        self.setUpCreds(custom_file_path, {
            "profiles.zosmf.properties.user": "user",
            "profiles.zosmf.properties.password": "password",
        })

        # Test
        prof_manager = ProfileManager(appname=self.custom_appname)
        prof_manager.config_dir = self.custom_dir
        props: dict = prof_manager.load(profile_name="lpar1.zosmf")
        self.assertEqual(prof_manager.config_filepath, custom_file_path)

        expected_props = {
            "host": "example1.com",
            "rejectUnauthorized": True,
            "port": 443
        }
        self.assertEqual(props, expected_props)

    @patch("keyring.get_password", side_effect=keyring_get_password)
    def test_profile_loading_with_user_overriden_properties(self, get_pass_func):
        """
        Test overriding of properties from user config,
        also load by profile_name correctly populating fields from base profile
        and secure credentials
        """

        cwd_up_dir_path = os.path.dirname(CWD)
        cwd_up_file_path = os.path.join(cwd_up_dir_path, "zowe.config.json")
        os.chdir(CWD)
        shutil.copy(self.original_file_path, cwd_up_file_path)
        shutil.copy(self.original_user_file_path, cwd_up_dir_path)

        self.setUpCreds(cwd_up_file_path, {
            "profiles.zosmf.properties.user": "user",
            "profiles.zosmf.properties.password": "password",
        })

        # Test
        prof_manager = ProfileManager()
        props: dict = prof_manager.load(profile_type="zosmf")
        self.assertEqual(prof_manager.config_filepath, cwd_up_file_path)

        expected_props = {
            "host": "zowe.test.user.cloud",
            "rejectUnauthorized": False,
            "user": "user",
            "password": "password",
            "port": 10000,
        }
        self.assertEqual(props, expected_props)

    @patch("keyring.get_password", side_effect=keyring_get_password)
    def test_profile_loading_exception(self, get_pass_func):
        """
        Test correct exceptions are being thrown when a profile is
        not found.

        Only the filename will be set
        """
        with self.assertWarns(custom_warnings.ProfileNotFoundWarning):
            # Setup
            cwd_up_dir_path = os.path.dirname(CWD)
            cwd_up_file_path = os.path.join(
                cwd_up_dir_path, f"{self.custom_appname}.config.json"
            )
            os.chdir(CWD)
            shutil.copy(self.original_file_path, cwd_up_file_path)

            # Test
            config_file = ConfigFile(name=self.custom_appname, type="team_config")
            props: dict = config_file.get_profile(profile_name="non_existent_profile")

    @patch("keyring.get_password", side_effect=keyring_get_password_exception)
    def test_secure_props_loading_warning(self, get_pass_func):
        """
        Test correct warnings are being thrown when secure properties
        are not found in keyring.

        Only the config folder will be set
        """
        with self.assertWarns(custom_warnings.SecurePropsNotFoundWarning):
            # Setup
            custom_file_path = os.path.join(self.custom_dir, "zowe.config.json")
            shutil.copy(self.original_file_path, custom_file_path)

            # Test
            prof_manager = ProfileManager()
            prof_manager.config_dir = self.custom_dir
            props: dict = prof_manager.load("base")
            
    @patch("sys.platform", "win32")
    @patch("zowe.core_for_zowe_sdk.CredentialManager._retrieve_credential")
    def test_load_secure_props(self, retrieve_cred_func):
        """
        Test loading secure_props from keyring or storage.
        """
        service_name = constants["ZoweServiceName"]
        # Setup - copy profile to fake filesystem created by pyfakefs
        cwd_up_dir_path = os.path.dirname(CWD)
        cwd_up_file_path = os.path.join(cwd_up_dir_path, "zowe.config.json")
        os.chdir(CWD)
        shutil.copy(self.original_file_path, cwd_up_file_path)
        credential = {
            cwd_up_file_path:
            {
            "profiles.base.properties.user": "user",
            "profiles.base.properties.password": "password"
            }
        }
        self.setUpCreds(cwd_up_file_path, credential)
        base64_encoded_credential = base64.b64encode(commentjson.dumps(credential).encode()).decode()
        encoded_credential = base64_encoded_credential.encode('utf-16le').decode()
        retrieve_cred_func.return_value = encoded_credential

        # call the load_secure_props method
        credential_manager = CredentialManager()
        credential_manager.load_secure_props()
        retrieve_cred_func.assert_called_once_with(service_name)
        # Verify the secure_props
        expected_secure_props = credential
        self.assertEqual(credential_manager.secure_props, expected_secure_props)

    @patch("sys.platform", "win32")
    @patch("keyring.delete_password")
    def test_delete_credential(self, delete_pass_func):
        """
        Test the delete_credential method for deleting credentials from keyring.
        """
        def side_effect(*args, **kwargs):
            if side_effect.counter < 2:
                side_effect.counter += 1
                raise keyring.errors.PasswordDeleteError
            else:
                return None
        side_effect.counter = 0

        # custom side effect function for the mock
        delete_pass_func.side_effect = side_effect
        credential_manager = CredentialManager()
        service_name = constants['ZoweServiceName']
        account_name = constants['ZoweAccountName']
        # Delete the credential
        credential_manager.delete_credential(service_name, account_name)
        expected_calls = [
            mock.call(service_name, account_name),
            mock.call(f"{service_name}-1", f"{account_name}-1"),
        ]
        delete_pass_func.assert_has_calls(expected_calls)

    @patch("sys.platform", "win32")
    @patch("keyring.get_password", side_effect=["password", None, "part1", "part2\0", None])
    def test_retrieve_credential(self, get_pass_func):
        """
        Test the _retrieve_credential method for retrieving credentials from keyring.
        """
        credential_manager = CredentialManager()
        service_name = f"{constants['ZoweServiceName']}/{constants['ZoweAccountName']}"

        # Scenario 1: Retrieve password directly
        expected_password1 = "password".encode('utf-16le').decode()
        expected_password1 = expected_password1[:-1]
        retrieve_credential1 = credential_manager._retrieve_credential(constants['ZoweServiceName'])
        self.assertEqual(retrieve_credential1, expected_password1)
        get_pass_func.assert_called_with(service_name, constants["ZoweAccountName"])

        # Scenario 2: Retrieve password in parts
        expected_password2 = "part1part2".encode('utf-16le').decode()
        retrieve_credential2 = credential_manager._retrieve_credential(constants['ZoweServiceName'])
        retrieve_credential2 = retrieve_credential2[:-1]
        self.assertEqual(retrieve_credential2, expected_password2)
        get_pass_func.assert_any_call(service_name, constants["ZoweAccountName"])
        get_pass_func.assert_any_call(f"{service_name}-1", f"{constants['ZoweAccountName']}-1")
        get_pass_func.assert_any_call(f"{service_name}-2", f"{constants['ZoweAccountName']}-2")

    @patch("sys.platform", "win32")
    @patch("keyring.get_password", side_effect=[None,None])
    def test_retrieve_credential_encoding_errors(self, get_pass_func):
        """
        Test the _retrieve_credential method for handling encoding errors and None values.
        """
        service_name = f"{constants['ZoweServiceName']}/{constants['ZoweAccountName']}"
        result=CredentialManager._retrieve_credential(constants['ZoweServiceName'])
        self.assertIsNone(result)
        get_pass_func.assert_called_with(f"{service_name}-1", f"{constants['ZoweAccountName']}-1")


    @patch("sys.platform", "win32")
    @patch("keyring.set_password")
    @patch("zowe.core_for_zowe_sdk.CredentialManager._retrieve_credential")
    @patch("zowe.core_for_zowe_sdk.CredentialManager.delete_credential")
    def test_save_secure_props_normal_credential(self, delete_pass_func, retrieve_cred_func, set_pass_func):
        """
        Test the save_secure_props method for saving credentials to keyring.
        """

        # Set up mock values and expected results
        service_name = constants["ZoweServiceName"] + "/" + constants["ZoweAccountName"]
        # Setup - copy profile to fake filesystem created by pyfakefs
        cwd_up_dir_path = os.path.dirname(CWD)
        cwd_up_file_path = os.path.join(cwd_up_dir_path, "zowe.config.json")
        os.chdir(CWD)
        shutil.copy(self.original_file_path, cwd_up_file_path)
        credential = {
            cwd_up_file_path:
            {
            "profiles.base.properties.user": "samadpls",
            "profiles.base.properties.password": "password"
            }
        }
        self.setUpCreds(cwd_up_file_path,credential)
        encoded_credential = base64.b64encode(commentjson.dumps(credential).encode()).decode()
        retrieve_cred_func.return_value = None

        CredentialManager.secure_props =  credential
        CredentialManager.save_secure_props()
        # delete the existing credential
        delete_pass_func.return_value = None
        # Verify the keyring function call
        set_pass_func.assert_called_once_with(
            service_name,
            constants['ZoweAccountName'],
            encoded_credential
        )

    @patch("sys.platform", "win32")
    @patch("zowe.core_for_zowe_sdk.CredentialManager._retrieve_credential")
    @patch("keyring.set_password")
    @patch("zowe.core_for_zowe_sdk.CredentialManager.delete_credential")
    def test_save_secure_props_exceed_limit(self, delete_pass_func, set_pass_func, retrieve_cred_func):
        
        # Set up mock values and expected results
        service_name = constants["ZoweServiceName"] + "/" + constants["ZoweAccountName"]
        # Setup - copy profile to fake filesystem created by pyfakefs
        cwd_up_dir_path = os.path.dirname(CWD)
        cwd_up_file_path = os.path.join(cwd_up_dir_path, "zowe.config.json")
        os.chdir(CWD)
        shutil.copy(self.original_file_path, cwd_up_file_path)
        credential = {
            cwd_up_file_path:
            {
            "profiles.base.properties.user": "user",
            "profiles.base.properties.password": "a" * (constants["WIN32_CRED_MAX_STRING_LENGTH"] + 1)
            }
        }
        self.setUpCreds(cwd_up_file_path, credential)
        base64_encoded_credential = base64.b64encode(commentjson.dumps(credential).encode()).decode()
        encoded_credential = base64_encoded_credential.encode('utf-16le').decode()
        retrieve_cred_func.return_value = encoded_credential

        CredentialManager.secure_props =  credential
        CredentialManager.save_secure_props()

        # delete the existing credential
        delete_pass_func.return_value = None

        expected_calls = []
        chunk_size = constants["WIN32_CRED_MAX_STRING_LENGTH"]
        chunks = [base64_encoded_credential[i: i + chunk_size] for i in range(0, len(base64_encoded_credential), chunk_size)]
        chunks[-1] += "\0"
        for index, chunk in enumerate(chunks, start=1):
            field_name = f"{constants['ZoweAccountName']}-{index}"
            service_names = f"{service_name}-{index}"
            password=(chunk + '\0' *(len(chunk)%2)).encode().decode('utf-16le')
            expected_calls.append(mock.call(
                service_names,
                field_name,
                password
            ))
        set_pass_func.assert_has_calls(expected_calls)

        

    @patch("keyring.get_password", side_effect=keyring_get_password)
    def test_profile_loading_with_env_variables(self, get_pass_func):
        """
        Test loading of correct file given a filename and directory,
        also load by profile_name correctly populating fields from custom
        profile and secure credentials
        """
        # Setup - copy profile to fake filesystem created by pyfakefs
        os.environ["ZOWE_OPT_HOST"] = "aaditya"
        custom_file_path = os.path.join(self.custom_dir, "zowe.config.json")
        shutil.copy(self.original_nested_file_path, custom_file_path)
        shutil.copy(self.original_schema_file_path, self.custom_dir)
        os.chdir(self.custom_dir)

        self.setUpCreds(custom_file_path, {
            "profiles.zosmf.properties.user": "user",
            "profiles.zosmf.properties.password": "password",
        })

        # Test
        prof_manager = ProfileManager(appname="zowe")
        prof_manager.config_dir = self.custom_dir
        props: dict = prof_manager.load(profile_name="lpar1.zosmf", override_with_env=True)

        expected_props = {
            "host": "aaditya",
            "rejectUnauthorized": True,
            "port": 443,
        }
        self.assertEqual(props, expected_props)

    @mock.patch("warnings.simplefilter")
    @mock.patch("warnings.resetwarnings")
    def test_get_highest_priority_layer(self, mock_resetwarnings, mock_simplefilter):
        """
        Test that get_highest_priority_layer returns the highest priority layer with a valid profile data dictionary.
        """
        # Set up mock profiles in the layers
        project_user_config = mock.MagicMock(spec=ConfigFile)
        project_user_config.find_profile.return_value = mock.MagicMock()
        project_user_config.find_profile.return_value.data = {"profiles": "zosmf"}
        
        # Set up the ProfileManager
        profile_manager = ProfileManager()
        profile_manager.project_user_config = project_user_config
        profile_manager._show_warnings = False
        project_user_config.get_profile_name_from_path.return_value = "zosmf"
        # Call the function being tested
        result_layer = profile_manager.get_highest_priority_layer("zosmf")
        
        # Assert the results
        self.assertEqual(result_layer, project_user_config)
        mock_simplefilter.assert_called_with("ignore")
        mock_resetwarnings.assert_called()

    @patch("zowe.core_for_zowe_sdk.ProfileManager.get_highest_priority_layer")
    def test_profile_manager_set_property(self, get_highest_priority_layer_mock):
        """
        Test that set_property calls the set_property method of the highest priority layer.
        """
        json_path = "profiles.zosmf.properties.user"
        value = "samadpls"
        secure = True

        # Set up mock for the highest priority layer
        highest_priority_layer_mock = mock.MagicMock(spec=ConfigFile)
        get_highest_priority_layer_mock.return_value = highest_priority_layer_mock

        profile_manager = ProfileManager()

        # Mock the behavior of _set_property method in highest_priority_layer
        highest_priority_layer_mock.set_property.return_value = None

        # Call the method being tested
        profile_manager.set_property(json_path, value, secure)

        # Assert the method calls
        highest_priority_layer_mock.set_property.assert_called_with(json_path, value, secure=secure)


    @patch("zowe.core_for_zowe_sdk.ConfigFile.save")
    @patch("zowe.core_for_zowe_sdk.CredentialManager.save_secure_props")
    def test_profile_manager_save(self, mock_save_secure_props, mock_save):
        """
        Test that save calls the save method of all layers.
        """
        profile_manager = ProfileManager()
        profile_manager.save()
        expected_calls = [call(False) for _ in range(4)]
        mock_save.assert_has_calls(expected_calls)
        mock_save_secure_props.assert_called_once() 
    
    @mock.patch("zowe.core_for_zowe_sdk.ProfileManager.get_highest_priority_layer")
    def test_profile_manager_set_profile(self, get_highest_priority_layer_mock):
        """
        Test that set_profile calls the set_profile method of the highest priority layer.
        """
        profile_path = "profiles.zosmf"
        profile_data = {
            "properties": {
                "user": "admin",
                "password": "password1"
            }
        }

        highest_priority_layer_mock = mock.MagicMock(spec=ConfigFile)
        get_highest_priority_layer_mock.return_value = highest_priority_layer_mock
        profile_manager = ProfileManager()

        highest_priority_layer_mock.set_profile.return_value = None
        profile_manager.set_profile(profile_path, profile_data)

        highest_priority_layer_mock.set_profile.assert_called_with(profile_path, profile_data)

    @mock.patch("zowe.core_for_zowe_sdk.ConfigFile.get_profile_path_from_name")
    def test_set_or_create_nested_profile(self, mock_get_profile_path):
        """
        Test that __set_or_create_nested_profile calls the get_profile_path_from_name method and sets the profile data.
        """
        mock_get_profile_path.return_value = "profiles.zosmf"
        config_file = ConfigFile( name="zowe_abcd", type="User Config", profiles={})
        profile_data = {
            "properties": {
                "user": "samadpls",
                "password": "password1"
            } 
        }
        config_file._ConfigFile__set_or_create_nested_profile("zosmf", profile_data)
        expected_profiles = {
            "zosmf": {
                "properties": {
                    "user": "samadpls",
                    "password": "password1"
                }
            }
        }
        self.assertEqual(config_file.profiles, expected_profiles)

    @mock.patch("zowe.core_for_zowe_sdk.ConfigFile.find_profile")
    def test_is_secure(self, mock_find_profile):
        """
        Test that __is_secure returns True if the property is secure and False otherwise.
        """
        config_file = ConfigFile(name="zowe_abcd", type="User Config", profiles={})
        mock_find_profile.return_value = {
                                        "properties": {"user":"samadpls"},
                                        "secure": ["password"]
                                        }
        is_secure_secure = config_file._ConfigFile__is_secure("zosmf", "password")
        is_secure_non_secure = config_file._ConfigFile__is_secure("zosmf", "user")

        self.assertTrue(is_secure_secure)
        self.assertFalse(is_secure_non_secure)

    @mock.patch("zowe.core_for_zowe_sdk.ConfigFile.get_profile_name_from_path")
    @mock.patch("zowe.core_for_zowe_sdk.ConfigFile.find_profile")
    @mock.patch("zowe.core_for_zowe_sdk.ConfigFile._ConfigFile__is_secure")
    def test_config_file_set_property(self, mock_is_secure, mock_find_profile, mock_get_profile_name):
        """
        Test that set_property calls the __is_secure, find_profile and get_profile_name_from_path methods.
        """
        config_file = ConfigFile(name="zowe_abcd", type="User Config", profiles= {})

        mock_is_secure.return_value = False
        mock_find_profile.return_value = {"properties": {"port": 1443}, "secure": []}
        mock_get_profile_name.return_value = "zosmf"

        config_file.set_property("profiles.zosmf.properties.user", "admin", secure=True)

        mock_is_secure.assert_called_with("zosmf", "user")
        mock_find_profile.assert_called_with("zosmf", config_file.profiles)
        mock_get_profile_name.assert_called_with("profiles.zosmf.properties.user")
        self.assertEqual(config_file.profiles, {
            "zosmf": {
                "properties": {"port": 1443},
                "secure": ["user"]
            }
        })    

    def test_get_profile_name_from_path(self):
        """
        Test that get_profile_name_from_path returns the profile name from the path.
        """
        config_file = ConfigFile(name="zowe_abcd", type="User Config")
        profile_name = config_file.get_profile_name_from_path("profiles.lpar1.profiles.zosmf.properties.user")
        self.assertEqual(profile_name, "lpar1.zosmf")    
    
    def test_get_profile_path_from_name(self):
        """
        Test that get_profile_path_from_name returns the profile path from the name.
        """
        config_file = ConfigFile(name="zowe_abcd", type="User Config")
        profile_path_1 = config_file.get_profile_path_from_name("lpar1.zosmf")
        self.assertEqual(profile_path_1, "profiles.lpar1.profiles.zosmf")

    def test_config_file_set_profile(self):
        """
        Test the set_profile method.
        """
        cwd_up_dir_path = os.path.dirname(CWD)
        cwd_up_file_path = os.path.join(cwd_up_dir_path, "zowe.config.json")
        os.chdir(CWD)
        shutil.copy(self.original_file_path, cwd_up_file_path)
        initial_profiles = {
            "lpar1": {
                "profiles": {
                    "zosmf": {
                        "properties": {
                            "port": 1443
                        },
                        "secure": []
                    }
                }
            }
        }
        config_file = ConfigFile("User Config", "zowe.config.json", cwd_up_dir_path , profiles=initial_profiles)
        profile_data = {
            "type": "zosmf",
            "properties": {
                "port": 443,
                "user": "abc",
                "password": "def"
            },
            "secure": ["user", "password"]
        }

        with patch("zowe.core_for_zowe_sdk.ConfigFile.get_profile_name_from_path", return_value="lpar1.zosmf"):
            with patch("zowe.core_for_zowe_sdk.ConfigFile.find_profile", return_value=initial_profiles["lpar1"]["profiles"]["zosmf"]):
                config_file.set_profile("profiles.lpar1.profiles.zosmf", profile_data)

        expected_secure_props = {
            cwd_up_file_path: {
                "profiles.lpar1.profiles.zosmf.properties.user": "abc",
                "profiles.lpar1.profiles.zosmf.properties.password": "def"
            }
        }
        expected_profiles = {
            "lpar1": {
                "profiles": {
                    "zosmf": {
                        'type': 'zosmf',
                        "properties": {
                            "port": 443,
                        },
                        "secure": ["user", "password"]
                    }
                }
            }
        }
        self.assertEqual(CredentialManager.secure_props, expected_secure_props)
        self.assertEqual(config_file.profiles, expected_profiles)
    
    @patch("zowe.core_for_zowe_sdk.CredentialManager.save_secure_props")
    def test_config_file_save(self, mock_save_secure_props):
        """
        Test saving a config file with secure properties.
        """
        cwd_up_dir_path = os.path.dirname(CWD)
        cwd_up_file_path = os.path.join(cwd_up_dir_path, "zowe.config.json")
        os.chdir(CWD)
        shutil.copy(self.original_file_path, cwd_up_file_path)
        config_data = {
            "profiles": {
                "zosmf": {
                    "properties": {
                        "user": "admin",
                        "port": 1443
                    },
                    "secure": ["user"]
                }
            }
        } 
        with patch("builtins.open", mock.mock_open()) as mock_file:
            config_file = ConfigFile("User Config", "zowe.config.json", cwd_up_dir_path , profiles=config_data.copy())
            config_file.jsonc = config_data
            config_file.save()

            mock_save_secure_props.assert_called_once()
            mock_file.assert_called_once_with(cwd_up_file_path, 'w')
            mock_file.return_value.__enter__.return_value.write.asser_called()
            

class TestValidateConfigJsonClass(unittest.TestCase):
    """Testing the validate_config_json function"""

    def test_validate_config_json_valid(self):
        """Test validate_config_json with valid config.json matching schema.json"""
        path_to_config = FIXTURES_PATH + "/zowe.config.json"
        path_to_schema = FIXTURES_PATH + "/zowe.schema.json"

        config_json = commentjson.load(open(path_to_config))
        schema_json = commentjson.load(open(path_to_schema))

        expected = validate(config_json, schema_json)
        result = validate_config_json(path_to_config, path_to_schema)

        self.assertEqual(result, expected)

    def test_validate_config_json_invalid(self):
        """Test validate_config_json with invalid config.json that does not match schema.json"""
        path_to_invalid_config = FIXTURES_PATH + "/invalid.zowe.config.json"
        path_to_invalid_schema = FIXTURES_PATH + "/invalid.zowe.schema.json"

        invalid_config_json = commentjson.load(open(path_to_invalid_config))
        invalid_schema_json = commentjson.load(open(path_to_invalid_schema))

        with self.assertRaises(ValidationError) as expected_info:
            validate(invalid_config_json, invalid_schema_json)

        with self.assertRaises(ValidationError) as actual_info:
            validate_config_json(path_to_invalid_config, path_to_invalid_schema)

        self.assertEqual(str(actual_info.exception), str(expected_info.exception))
    
    