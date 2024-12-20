import cv2
import sys
from ArUCo_Markers_Pose.utils import ARUCO_DICT, rvec_to_quaternion
import argparse
import os
import json
from datetime import datetime
import numpy as np

DEBUG = False

class Aruco_pose():
    keep_mkv = True  
    ext = '.mp4'
    camera_id = 0
    
    def __init__(self, 
                 video_path:str, 
                 EDMO_type:str="Snake",
                 show:bool=False,
                 aruco_marker_estimation_path:str="./ArUCo_Markers_Pose/", 
                 aruco_dict_type:str="DICT_4X4_100") -> None:
        if aruco_marker_estimation_path[-1] != "/":
            aruco_marker_estimation_path += "/"
        
        self.k = np.load(f"{aruco_marker_estimation_path}calibration_matrix.npy")
        self.d = np.load(f"{aruco_marker_estimation_path}distortion_coefficients.npy")
        self.aruco_dict_type: int = ARUCO_DICT[aruco_dict_type]
        self.show = show
        if video_path[0] != '/':
            video_path = '/' + video_path
        self.video_path = os.getcwd() + video_path
        self.EDMO_type = EDMO_type
        
        if self.keep_mkv:
            self.ext = '.mkv'
        
        # Get the valid Aruco ids for the EDMO (format: {leg0 leg1 leg2 leg3 middle corner0 corner1 corner2 corner3})
        self.valid_tags = []
        try:
            with open(f'{aruco_marker_estimation_path}tags/{EDMO_type}.txt', 'r') as f:
                content = f.read().split(' ')
                for tag_id in content:
                    self.valid_tags.append(int(tag_id))
        except FileNotFoundError:
            print(f"Error: The file tags/{EDMO_type}.txt is missing.")
            return
        
        self.first_frame = True
        self.M_cam_to_first_aruco = np.eye(4)  # Transformation matrix from the camera frame to the world frame (= position of the marker on the first video frame)
        self.M_first_aruco_to_cam = np.eye(4)  #                                world frame to the camera frame


    def get_aruco_pose(self, frame, origin):
        '''
        frame - Frame from the video stream
        aruco_dict_type - Type of Aruco dictionary used
        matrix_coefficients - Intrinsic matrix of the calibrated camera
        distortion_coefficients - Distortion coefficients associated with your camera
        valid_tags - The id of the Aruco markers we want to detect

        return: - A dictionary with the valid_tags as keys and its position if detected
        '''
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        aruco_dict = cv2.aruco.getPredefinedDictionary(self.aruco_dict_type)
        parameters = cv2.aruco.DetectorParameters()

        detector = cv2.aruco.ArucoDetector(aruco_dict, parameters)
        corners, ids, rejected_img_points = detector.detectMarkers(gray)

        if ids is not None and origin not in ids:
            return None
        pos_dict = {}
        # If markers are detected
        if len(corners) > 0:
            if self.first_frame and origin in ids:
                index = np.where(ids==origin)[0][0]
                corners = [corners[index]] + [c for i, c in enumerate(corners) if i != index]
                ids = [origin] + [el for el in ids if el != origin]
            for i in range(0, len(ids)):
                if ids[i] not in self.valid_tags:
                    continue
                marker_length = 0.04
                if ids[i] == 98:
                    marker_length = 0.09
                object_points = np.array([[-marker_length / 2, marker_length / 2, 0],
                                        [marker_length / 2, marker_length / 2, 0],
                                        [marker_length / 2, -marker_length / 2, 0],
                                        [-marker_length / 2, -marker_length / 2, 0]])

                ret, rvec, tvec = cv2.solvePnP(object_points, corners[i], self.k, self.d)
                if ret:
                    x, y, z = tvec.flatten()
                    # Convert rvec to a rotation matrix
                    R, _ = cv2.Rodrigues(rvec)

                    M_cam_to_aruco = np.eye(4)
                    M_cam_to_aruco[:3, :3] = R
                    M_cam_to_aruco[:3, 3] = [x, y, z]
                    t_rel = None
                    rvec_rel = None
                    # Record the positions of the aruco markers with regard to the initial position
                    if self.first_frame:
                        if ids[i] == origin:
                            if 1 - abs(rvec_to_quaternion(rvec)[0]) > 0.1:
                                return None 
                            print(f'World coordinate is computed from marker {ids[i]}')
                            origin_coord = np.array([0, 0, 0]) 

                            match ids[i]:
                                case 4:
                                    pass
                                case 3:
                                    origin_coord = np.array([1.70, 0, 0]) 
                                case 2:
                                    origin_coord = np.array([1.70, -1.10, 0]) 
                                case 1:
                                    origin_coord = np.array([0, -1.10, 0]) 

                            self.M_cam_to_first_aruco = M_cam_to_aruco
                            
                            T_to_true_origin = np.zeros((4,4))
                            T_to_true_origin[:3, 3] = origin_coord  # shift to the origin
                            
                            # Record the transformation matrices
                            self.M_first_aruco_to_cam = np.linalg.inv(self.M_cam_to_first_aruco) + T_to_true_origin
                            
                            pos_dict[f'{ids[i]}'] = [origin_coord.tolist(), np.array([0, 0, 0]).tolist()]
                            self.first_frame = False
                            
                            if DEBUG:
                                print(f'cam to first aruco: \n')
                                print(self.M_cam_to_first_aruco)
                                print(f'True origin to cam: \n')
                                print(self.M_first_aruco_to_cam)
                    else:
                        M_marker_to_first_aruco = np.dot(self.M_first_aruco_to_cam, M_cam_to_aruco)

                        # Extract the relative rotation and translation vectors from the transformation matrix
                        R_rel = M_marker_to_first_aruco[:3, :3]
                        t_rel = M_marker_to_first_aruco[:3, 3]

                        # Convert the relative rotation matrix back to rvec
                        rvec_rel, _ = cv2.Rodrigues(R_rel)
                        pos_dict[f'{ids[i]}'] = [t_rel.tolist(), rvec_rel.flatten().tolist()]
                        
                    if self.show:
                        # Draw a square around the markers
                        cv2.aruco.drawDetectedMarkers(frame, corners)

                        # Draw axis
                        cv2.drawFrameAxes(frame, self.k, self.d, rvec, tvec, marker_length)
                        a, b, c = rvec.flatten()
                        if DEBUG and rvec is not None:
                            print(f'{ids[i]} : quaternions= {rvec_to_quaternion(rvec)} / {t_rel} / {tvec.tolist()}')
                        
                        if ids[i] == 4:
                            if t_rel is None:
                                pass
                            else:
                                cv2.putText(frame, f'x: {t_rel[0]:.2f}', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 2)
                                cv2.putText(frame, f'y: {t_rel[1]:.2f}', (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 2)
                                cv2.putText(frame, f'z: {t_rel[2]:.2f}', (10, 110), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 2)
                                cv2.putText(frame, f'a: {rvec_rel[0][0]:.2f}', (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 2)
                                cv2.putText(frame, f'b: {rvec_rel[1][0]:.2f}', (10, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 2)
                                cv2.putText(frame, f'c: {rvec_rel[2][0]:.2f}', (10, 230), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 2)
        return pos_dict


    def pose_estimation(self):
        video = cv2.VideoCapture(self.video_path)
        fps = video.get(cv2.CAP_PROP_FPS)
        print(f'fps: {fps}')
        use_video = self.video_path != self.camera_id
        if use_video:
            if not os.path.exists(self.video_path):
                print(f"File {self.video_path} not found when getting the video")
                sys.exit(0)

            name, ext = os.path.splitext(self.video_path)
            if ext.lower() != ".mp4" and ext.lower() != ".mkv":
                print(f"Wrong video file format {ext} is not supported")
                sys.exit(0)
        else: # Record the camera feed
            frame_width = int(video.get(3)) 
            frame_height = int(video.get(4)) 
            
            size = (frame_width, frame_height) 
            file_date = datetime.now().strftime("%d-%m-%Y %H-%M-%S")
            
            date, time = file_date.replace('-', '.').split(' ')
            if not os.path.exists('Video data'):
                os.makedirs(f'Video data')
            if not os.path.exists('Video data/' + date):
                os.makedirs(f'Video data/{date}')
            if not os.path.exists(f'Video data/{date}/{time}'):
                os.makedirs(f'Video data/{date}/{time}')    
            self.video_path = f'Video data/{date}/{time}/{file_date}.mkv'
            
            print(f'Video file will be stored at {self.video_path}')
            output_video = cv2.VideoWriter(self.video_path,  
                                    cv2.VideoWriter_fourcc(*'MJPG'), 
                                    fps, size) 

        frame_index = 0
        dict_all_pos = {}
        while True:
            ret, frame = video.read()
            if not ret:
                break 
            if not use_video:
                output_video.write(frame)
            
            # Improve detection by applying smoothing
            # frame = cv2.bilateralFilter(frame, d=9, sigmaColor=75, sigmaSpace=75)
            output = None
            for i in range(4, 0, -1):
                origin = i if i != 1 else 0
                output = self.get_aruco_pose(frame, origin=origin)
                if output is not None:
                    break
            if not output:
                frame_index += 1
                continue 

            if self.show or not use_video:
                scaled_frame = cv2.resize(frame, (960, 540))
                cv2.imshow('Estimated Pose', scaled_frame)
                # UNCOMMENT TO VIEW FRAME PER FRAME
                # while True:
                #     key = cv2.waitKey(1) & 0xFF
                #     if key == ord('n'):
                #         break  
                key = cv2.waitKey(10) & 0xFF
                if key == ord('q'):
                    break
                
                                    
            if len(output) > 0:
                for tag_id, v in output.items():
                    if tag_id not in dict_all_pos:
                        dict_all_pos[tag_id] = {}
                    dict_all_pos[tag_id][int(frame_index)] = v
            frame_index += 1
        video.release()
        if not use_video:
            output_video.release()
        cv2.destroyAllWindows()
        f = open(f"{os.path.dirname(self.video_path)}/marker_pose.log", "w")
        json.dump(dict_all_pos, f)

if __name__ == '__main__':
    # Example usage : 
    # python -m ArUCo_Markers_Pose.pose_estimation -v 'ArUCo_Markers_Pose/Videos/GX010458.MP4' -s True -edmo 'Snake' -p ./ArUCo_Markers_Pose/
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--path", default="ArUCo_Markers_Pose", help="Path to ArUCo_Markers_Pose folder")
    ap.add_argument("-t", "--type", type=str, default="DICT_4X4_100", help="Type of ArUCo tag to detect")
    ap.add_argument("-v", "--video", type=str, default=0, help="Path to video or uses laptop camera feed by defaut)")
    ap.add_argument("-edmo", "--EDMO_type", type=str, default='Spider', help="Type of EDMO (Spider, Snake, ...)")
    ap.add_argument("-s", "--show", type=bool, default=False, help="Show output frame")
    args = vars(ap.parse_args())

    aruco_dict_type = args["type"]
    video_path = args['video']
    EDMO_type = args['EDMO_type']
    show = args['show']
    path = args["path"]

    aruco_pose = Aruco_pose(video_path, EDMO_type, show=show, aruco_dict_type=aruco_dict_type,aruco_marker_estimation_path=path)
    aruco_pose.pose_estimation()
