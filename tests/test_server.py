"""Tests for the Cinema 4D MCP Server."""

import unittest
import socket
import json
from contextlib import asynccontextmanager
from unittest.mock import patch, MagicMock

from cinema4d_mcp.server import (
    send_to_c4d,
    C4DConnection,
    inspect_redshift_materials,
)

class TestC4DServer(unittest.TestCase):
    """Test cases for Cinema 4D server functionality."""

    def test_connection_disconnected(self):
        """Test behavior when connection is disconnected."""
        connection = C4DConnection(sock=None, connected=False)
        result = send_to_c4d(connection, {"command": "test"})
        self.assertIn("error", result)
        self.assertEqual(result["error"], "Not connected to Cinema 4D")

    @patch('socket.socket')
    def test_send_to_c4d(self, mock_socket):
        """Test sending commands to C4D with a mocked socket."""
        # Setup mock
        mock_instance = MagicMock()
        mock_instance.recv.return_value = b'{"result": "success"}\n'
        mock_socket.return_value = mock_instance
        
        # Create connection with mock socket
        connection = C4DConnection(sock=mock_instance, connected=True)
        
        # Test sending a command
        result = send_to_c4d(connection, {"command": "test"})
        
        # Verify command was sent correctly
        expected_send = b'{"command": "test"}\n'
        mock_instance.sendall.assert_called_once()
        self.assertEqual(result, {"result": "success"})

    def test_send_to_c4d_exception(self):
        """Test error handling when sending fails."""
        # Create a socket that raises an exception
        mock_socket = MagicMock()
        mock_socket.sendall.side_effect = Exception("Test error")
        
        connection = C4DConnection(sock=mock_socket, connected=True)
        result = send_to_c4d(connection, {"command": "test"})
        
        self.assertIn("error", result)
        self.assertIn("Test error", result["error"])

class TestC4DTools(unittest.IsolatedAsyncioTestCase):
    """Test MCP tool wrappers that add formatting on top of socket responses."""

    async def test_inspect_redshift_materials_formats_json(self):
        """The Redshift inspector should send the right command and return JSON text."""

        @asynccontextmanager
        async def fake_connection():
            yield C4DConnection(sock=MagicMock(), connected=True)

        payload = {
            "status": "ok",
            "materials": [{"name": "RS Material.8", "type_id": 1036224}],
        }

        with patch("cinema4d_mcp.server.c4d_connection_context", fake_connection):
            with patch("cinema4d_mcp.server.send_to_c4d", return_value=payload) as mock_send:
                result = await inspect_redshift_materials(
                    material_name="RS Material.8",
                    include_preview=False,
                    include_graph=False,
                )

        self.assertEqual(json.loads(result), payload)
        mock_send.assert_called_once()

        command = mock_send.call_args.args[1]
        self.assertEqual(command["command"], "inspect_redshift_materials")
        self.assertEqual(command["material_name"], "RS Material.8")
        self.assertEqual(command["include_preview"], False)
        self.assertEqual(command["include_graph"], False)


if __name__ == '__main__':
    unittest.main()
