"""
ros_bridge.py - (선택) 규격 v0.2 기록을 ROS 2 로 발행. fire-detect --ros 일 때만 쓴다.

    /fire/<id>/status   odor_msgs/FireStatus     1 Hz
    /health/<id>        odor_msgs/DeviceHealth   10 초마다

필요: ROS 2 Jazzy + odor_msgs (moving-ver/ros2_ws/src/odor_msgs 를 빌드해 source).
감지와 차단은 ROS 없이도 동작한다. ROS 는 대시보드로 보내는 통로일 뿐이다.
"""
from __future__ import annotations

import rclpy
from rclpy.node import Node

from odor_msgs.msg import DeviceHealth, FireStatus

from .odor_json import fill_msg


class RosBridge:
    def __init__(self, device_id: str, node_name: str = "fire_detect"):
        rclpy.init()
        self.node = Node(node_name)
        self.pub_status = self.node.create_publisher(FireStatus, f"/fire/{device_id}/status", 10)
        self.pub_health = self.node.create_publisher(DeviceHealth, f"/health/{device_id}", 10)

    def publish(self, rec: dict) -> None:
        if rec["type"] == "fire_status":
            self.pub_status.publish(fill_msg(FireStatus(), rec))
        elif rec["type"] == "device_health":
            self.pub_health.publish(fill_msg(DeviceHealth(), rec))
        rclpy.spin_once(self.node, timeout_sec=0.0)

    def close(self) -> None:
        self.node.destroy_node()
        rclpy.try_shutdown()
