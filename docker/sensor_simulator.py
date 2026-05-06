#!/usr/bin/env python3
"""ROS sensor simulator for a differential drive robot.

Subscribes to /cmd_vel and publishes /odom, /imu/data, and /scan.
This provides realistic enough data for testing the ROS -> MQTT bridge.
"""
from __future__ import annotations

import math
import random

import rospy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Imu, LaserScan


class SensorSimulator:
    def __init__(self) -> None:
        rospy.init_node("sensor_simulator", anonymous=True)

        # Robot pose state
        self._x: float = 0.0
        self._y: float = 0.0
        self._yaw: float = 0.0
        self._vx: float = 0.0  # linear velocity (from /cmd_vel)
        self._vz: float = 0.0  # angular velocity (from /cmd_vel)
        self._last_time = rospy.Time.now()

        # Publishers
        self._odom_pub = rospy.Publisher("/odom", Odometry, queue_size=10)
        self._imu_pub = rospy.Publisher("/imu/data", Imu, queue_size=10)
        self._scan_pub = rospy.Publisher("/scan", LaserScan, queue_size=10)

        # Subscriber
        rospy.Subscriber("/cmd_vel", Twist, self._cmd_vel_cb)

        rospy.loginfo("[simulator] Sensor simulator started")
        rospy.loginfo("[simulator] Publishing: /odom (10Hz), /imu/data (10Hz), /scan (5Hz)")
        rospy.loginfo("[simulator] Subscribing: /cmd_vel")

    def _cmd_vel_cb(self, msg: Twist) -> None:
        self._vx = msg.linear.x
        self._vz = msg.angular.z

    def _update_pose(self) -> None:
        now = rospy.Time.now()
        dt = (now - self._last_time).to_sec()
        if dt <= 0.0 or dt > 1.0:  # guard against first iteration / time jumps
            self._last_time = now
            return
        self._last_time = now

        self._x += self._vx * math.cos(self._yaw) * dt
        self._y += self._vx * math.sin(self._yaw) * dt
        self._yaw += self._vz * dt

    def _yaw_to_quat(self) -> tuple[float, float]:
        """Return (z, w) quaternion components for a yaw-only rotation."""
        return (math.sin(self._yaw / 2.0), math.cos(self._yaw / 2.0))

    def _make_odometry(self) -> Odometry:
        self._update_pose()
        msg = Odometry()
        msg.header.stamp = rospy.Time.now()
        msg.header.frame_id = "odom"
        msg.child_frame_id = "base_link"
        z, w = self._yaw_to_quat()
        msg.pose.pose.position.x = self._x
        msg.pose.pose.position.y = self._y
        msg.pose.pose.orientation.z = z
        msg.pose.pose.orientation.w = w
        msg.twist.twist.linear.x = self._vx
        msg.twist.twist.angular.z = self._vz
        return msg

    def _make_imu(self) -> Imu:
        msg = Imu()
        msg.header.stamp = rospy.Time.now()
        msg.header.frame_id = "imu_link"
        z, w = self._yaw_to_quat()
        msg.orientation.z = z
        msg.orientation.w = w
        msg.angular_velocity.z = self._vz + random.gauss(0.0, 0.01)
        msg.linear_acceleration.x = random.gauss(0.0, 0.1)
        msg.linear_acceleration.y = random.gauss(0.0, 0.1)
        msg.linear_acceleration.z = random.gauss(9.81, 0.05)
        # -1 means "no covariance estimate"
        msg.orientation_covariance[0] = -1.0
        msg.angular_velocity_covariance[0] = -1.0
        msg.linear_acceleration_covariance[0] = -1.0
        return msg

    def _make_laserscan(self) -> LaserScan:
        msg = LaserScan()
        msg.header.stamp = rospy.Time.now()
        msg.header.frame_id = "laser_link"
        msg.angle_min = -math.pi
        msg.angle_max = math.pi
        msg.angle_increment = math.pi / 180.0  # 1 degree resolution
        msg.range_min = 0.1
        msg.range_max = 30.0
        n = int((msg.angle_max - msg.angle_min) / msg.angle_increment) + 1
        # Simulated wall at ~5m with noise
        msg.ranges = [max(0.15, random.gauss(5.0, 0.2)) for _ in range(n)]
        return msg

    def run(self) -> None:
        rate = rospy.Rate(10)  # 10 Hz main loop
        seq = 0
        while not rospy.is_shutdown():
            self._odom_pub.publish(self._make_odometry())
            self._imu_pub.publish(self._make_imu())
            if seq % 2 == 0:  # scan at 5 Hz
                self._scan_pub.publish(self._make_laserscan())
            seq += 1
            rate.sleep()


if __name__ == "__main__":
    try:
        sim = SensorSimulator()
        sim.run()
    except rospy.ROSInterruptException:
        pass
